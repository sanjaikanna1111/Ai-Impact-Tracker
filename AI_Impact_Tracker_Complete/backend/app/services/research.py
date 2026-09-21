import asyncio
import json
import logging
import re
import statistics
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, Field

from app.config import settings
from app.schemas import (
    ResearchRequest,
    BusinessUnderstanding,
    ProductCandidate,
    EvidenceItem,
    SearchResult,
)
from app.providers import (
    SerperProvider,
    BingGroundingProvider,
    JinaProvider,
    GeminiProvider,
    CompaniesHouseProvider,
    SECProvider,
    FXProvider,
    FMPProvider,
    GeminiUnavailableError,
)
from app.services.domain_validation import is_vendor_candidate, registrable
from app.services.scoring import overall, budget_fit
from app.services.value_model import build_value_assessment
from app.services.financial_extractor import (
    extract_deterministic_metrics,
    deduplicate_and_prioritise_metrics,
    find_candidate_excerpts,
    is_false_positive_snippet,
    parse_reporting_period,
)

logger = logging.getLogger("uvicorn.error")

REVIEW_DOMAINS = [
    "g2.com",
    "capterra.com",
    "trustpilot.com",
    "reddit.com",
    "peerspot.com",
    "gartner.com",
    "getapp.com",
    "softwareadvice.com",
    "trustradius.com",
    "youtube.com",
]

HIGH_QUALITY_DOMAINS = [
    ".gov",
    ".gov.uk",
    ".nhs.uk",
    ".edu",
    ".ac.uk",
    "sec.gov",
    "company-information.service.gov.uk",
]

REVIEW_SIGNALS = (
    "review",
    "reviews",
    "rating",
    "ratings",
    "pros",
    "cons",
    "feedback",
    "testimonial",
    "customer experience",
    "user experience",
    "complaint",
)


class CandidateSeed(BaseModel):
    product: str
    vendor: str
    vendor_url: str
    why_relevant: str = ""


class CandidateSeeds(BaseModel):
    candidates: list[CandidateSeed] = Field(default_factory=list)


class ProductAnalysis(BaseModel):
    product: str
    vendor: str
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)
    sector_relevance: str = ""
    goal_relevance: str = ""
    is_commercial_product: bool = True
    is_relevant: bool = True
    goal_fit: float = Field(ge=0, le=100)
    sector_fit: float = Field(ge=0, le=100)
    evidence_score: float = Field(ge=0, le=100)
    adoption_score: float = Field(ge=0, le=100)
    momentum_score: float = Field(ge=0, le=100)
    implementation_score: float = Field(ge=0, le=100)
    evidence: list[EvidenceItem] = Field(default_factory=list)


class BatchProductAnalyses(BaseModel):
    products: list[ProductAnalysis] = Field(default_factory=list)


class ReviewAssessment(BaseModel):
    source_url: str
    platform: str = "Web"
    sentiment: Literal[
        "positive",
        "neutral",
        "negative",
        "insufficient",
    ] = "insufficient"
    summary: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)
    themes: list[str] = Field(default_factory=list)


class CustomerImpactItem(BaseModel):
    customer: str
    application: str = ""
    metric: str = ""
    impact_value: float | None = None
    impact_unit: str = ""
    time_period: str = ""
    claim: str = ""
    source_url: str
    source_quality: Literal["high", "medium", "low"] = "medium"
    direction: str = ""
    impact_scope: Literal["total_operating_expenses", "process_cost", "labour_cost", "waiting_time", "throughput", "conversion", "revenue", "customer_satisfaction", "adoption_scale", "other", "unknown"] = "unknown"
    before_value: float | None = None
    after_value: float | None = None
    classification: Literal["financial", "operational"] = "operational"
    source_domain: str = ""
    source_type: str = ""
    confidence: float = Field(default=0.0, ge=0, le=1)


class CustomerReference(BaseModel):
    customer: str
    application: str = ""
    industry: str = ""
    source_url: str
    source_title: str = ""
    evidence_text: str = ""
    confidence: float = Field(default=0.0, ge=0, le=1)
    source_type: Literal["vendor_case_study", "vendor_social", "customer_authored", "independent_article", "technographic", "other"] = "other"


class DeepProductResearch(BaseModel):
    sentiment_score: float | None = Field(default=None, ge=0, le=100)
    sentiment_evidence_sufficient: bool = False

    positive_themes: list[str] = Field(default_factory=list)
    negative_themes: list[str] = Field(default_factory=list)

    review_assessments: list[ReviewAssessment] = Field(
        default_factory=list
    )

    customers: list[CustomerReference] = Field(
        default_factory=list
    )

    impacts: list[CustomerImpactItem] = Field(
        default_factory=list
    )

    impact_score: float = Field(
        default=50,
        ge=0,
        le=100,
    )

    annual_software_cost: float | None = None
    implementation_cost: float | None = None

    currency: str = "GBP"
    pricing_basis: str = ""

    pricing_confidence: float = Field(
        default=0,
        ge=0,
        le=1,
    )

    pricing_evidence: list[EvidenceItem] = Field(
        default_factory=list
    )

    quality_evidence: list[EvidenceItem] = Field(
        default_factory=list
    )

    risks: list[str] = Field(default_factory=list)


class BatchDeepProductItem(DeepProductResearch):
    product: str
    vendor: str = ""


class BatchDeepProductResearch(BaseModel):
    products: list[BatchDeepProductItem] = Field(default_factory=list)


class CompactDeepProductItem(BaseModel):
    """Bounded conclusions only; Python retains all raw evidence separately."""
    product: str
    vendor: str = ""
    review_assessments: list[ReviewAssessment] = Field(default_factory=list)
    customers: list[CustomerReference] = Field(default_factory=list)
    impacts: list[CustomerImpactItem] = Field(default_factory=list)
    annual_software_cost: float | None = None
    implementation_cost: float | None = None
    currency: str = ""
    pricing_basis: str = ""
    pricing_source_urls: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class CompactDeepAnalysis(BaseModel):
    products: list[CompactDeepProductItem] = Field(default_factory=list)


class FinancialWebExtraction(BaseModel):
    company_name: str
    revenue: float | None = None
    operating_costs: float | None = None
    operating_income: float | None = None
    adjusted_operating_profit: float | None = None
    profit_before_tax: float | None = None
    net_income: float | None = None
    total_assets: float | None = None
    total_liabilities: float | None = None
    cash: float | None = None
    operating_cash_flow: float | None = None
    staff_costs: float | None = None
    employees: int | None = None
    currency: str = "GBP"
    reporting_period: str = ""
    evidence: list[EvidenceItem] = Field(default_factory=list)


class ResearchService:
    def __init__(self):
        self.serper = SerperProvider()
        self.bing = BingGroundingProvider()
        self.jina = JinaProvider()
        self.gemini = GeminiProvider()
        self.ch = CompaniesHouseProvider()
        self.sec = SECProvider()
        self.fx = FXProvider()
        self.fmp = FMPProvider()
        self._financial_cache: dict[str, dict] = {}

    @staticmethod
    def _plain(value: str, limit: int = 900) -> str:
        value = re.sub(
            r"\s+",
            " ",
            str(value or ""),
        ).strip()

        return value[:limit]

    @staticmethod
    def _platform(url: str) -> str:
        domain = registrable(url)

        for d in REVIEW_DOMAINS:
            if d in domain:
                return {
                    "g2.com": "G2",
                    "capterra.com": "Capterra",
                    "trustpilot.com": "Trustpilot",
                    "reddit.com": "Reddit",
                    "peerspot.com": "PeerSpot",
                    "gartner.com": "Gartner",
                    "getapp.com": "GetApp",
                    "softwareadvice.com": "Software Advice",
                    "youtube.com": "YouTube",
                }.get(
                    d,
                    d,
                )

        return "Web"

    @staticmethod
    def _source_quality(
        url: str,
        vendor_domain: str = "",
    ) -> Literal["high", "medium", "low"]:
        low = (url or "").lower()
        domain = registrable(url)

        if any(
            x in low
            for x in HIGH_QUALITY_DOMAINS
        ):
            return "high"

        if any(
            d in domain
            for d in REVIEW_DOMAINS
        ):
            return "medium"

        if (
            vendor_domain
            and domain == vendor_domain
        ):
            return "medium"

        return "medium"

    @staticmethod
    def _is_relevant_review_hit(
        product: str,
        hit: SearchResult,
        vendor: str = "",
    ) -> bool:
        text = f"{hit.title} {hit.snippet}".lower()
        url = (hit.url or "").lower()
        product_text = product.lower().strip()
        vendor_text = vendor.lower().strip()
        text = (
            f"{hit.title} {hit.snippet}"
        ).lower()

        clean_text = re.sub(r"[^a-z0-9]", "", text)
        clean_product = re.sub(r"[^a-z0-9]", "", product_text)
        clean_vendor = re.sub(r"[^a-z0-9]", "", vendor_text)
        url = (
            hit.url or ""
        ).lower()

        tokens = [t for t in re.findall(r"[a-z0-9]+", product_text) if len(t) >= 3]
        v_tokens = [t for t in re.findall(r"[a-z0-9]+", vendor_text) if len(t) >= 3]
        product_text = (
            product.lower().strip()
        )

        tokens = [
            t
            for t in re.findall(
                r"[a-z0-9]+",
                product_text,
            )
            if len(t) >= 3
        ]

        product_match = (
            product_text in text
            or (clean_product and clean_product in clean_text)
            or (tokens and any(t in text for t in tokens if len(t) >= 4))
            or (tokens and len(tokens) >= 2 and all(t in text for t in tokens[:2]))
            or (vendor_text and vendor_text in text)
            or (clean_vendor and len(clean_vendor) >= 4 and clean_vendor in clean_text)
            or (v_tokens and any(t in text for t in v_tokens if len(t) >= 4))
            or (
                tokens
                and all(
                    t in text
                    for t in tokens[:2]
                )
            )
        )

        if not product_match:
            return False

        domain = registrable(hit.url).lower()
        review_domain = any(d in domain for d in REVIEW_DOMAINS)
        review_signal = any(signal in text or signal in url for signal in REVIEW_SIGNALS)

        return review_domain or review_signal

    @staticmethod
    def _discovery_source_type(hit: SearchResult, vendor_domain: str) -> str:
        """Label a search candidate for diagnostics; page evidence is still required."""
        domain = registrable(hit.url).lower()
        text = f"{hit.title} {hit.snippet} {hit.url}".lower()
        if domain and domain == vendor_domain.lower():
            if any(term in text for term in ("pricing", "price", "cost", "subscription", "licence", "license")):
                return "pricing_page"
            return "vendor_product_page" if any(term in text for term in ("product", "platform", "features", "solutions")) else "vendor_marketing_page"
        if any(review_domain in domain for review_domain in REVIEW_DOMAINS):
            return "independent_review"
        if any(term in text for term in ("case study", "customer story", "customer success", "testimonial")):
            return "customer_case_study" if "testimonial" not in text else "customer_testimonial"
        if any(term in text for term in ("implemented", "deployed", "implementation")):
            return "implementation_report"
        if any(term in text for term in ("roi", "savings", "cost reduction", "outcomes", "results")):
            return "independent_impact_report"
        if any(term in text for term in ("annual report", "financial statements", "companies house", "company registry")):
            return "financial_filing" if "companies house" not in text else "company_registry"
        return "generic_article" if text.strip() else "unknown"

    @staticmethod
    def _evidence_weight(
        item: EvidenceItem,
        vendor_domain: str,
    ) -> float:
        url = (
            item.source_url
            or ""
        )

        low = url.lower()

        domain = registrable(
            url
        )

        evidence_type = (
            item.evidence_type
            or ""
        ).lower()

        if any(
            x in low
            for x in HIGH_QUALITY_DOMAINS
        ):
            return 1.0

        if any(
            d in domain
            for d in REVIEW_DOMAINS
        ):
            return 0.85

        if (
            vendor_domain
            and domain == vendor_domain
        ):
            if (
                "case" in low
                or "case" in evidence_type
                or "customer" in evidence_type
            ):
                return 0.65

            if (
                "blog" in low
                or "article" in evidence_type
            ):
                return 0.45

            return 0.55

        if "press release" in evidence_type:
            return 0.55

        if any(
            x in low
            for x in (
                "linkedin.com",
                "x.com",
                "facebook.com",
                "youtube.com",
            )
        ):
            return 0.35

        return 0.75

    @staticmethod
    def _sic_sector_hint(
        sic_codes: list[str],
    ) -> str | None:
        if not sic_codes:
            return None

        code = str(
            sic_codes[0]
            or ""
        ).strip()

        if code.startswith("47"):
            return "Retail"

        if code.startswith("86"):
            return "Healthcare"

        if code.startswith(
            (
                "64",
                "65",
                "66",
            )
        ):
            return "Financial services"

        if code.startswith("62"):
            return "Technology"

        if code.startswith(
            (
                "49",
                "50",
                "51",
                "52",
                "53",
            )
        ):
            return "Transport and logistics"

        if code.startswith(
            (
                "55",
                "56",
            )
        ):
            return "Hospitality"

        if code.startswith("85"):
            return "Education"

        if code.startswith("84"):
            return "Public administration"

        if (
            len(code) >= 2
            and code[:2].isdigit()
            and 10 <= int(code[:2]) <= 33
        ):
            return "Manufacturing"

        return None

    async def _business_understanding(
        self,
        req: ResearchRequest,
    ):
        prompt = f"""
You are a business-process analyst.

Convert the user's business context into a precise research specification.

Sector:
{req.sector}

Business goal:
{req.business_goal}

Company size:
{req.company_size}

Employees:
{req.employees}

Adoption budget:
GBP {req.budget:,.0f}

Company:
{req.company_name or "not supplied"}

Country:
{req.company_country or "not supplied"}

Return practical processes, AI/software capabilities,
measurable KPIs, and 6-10 web search queries focused
on real commercial software products.

Do not recommend products yet.
"""

        try:
            return await self.gemini.structured(
                prompt,
                BusinessUnderstanding,
            )
        except Exception as exc:
            logger.warning(
                "[BUSINESS UNDERSTANDING] Gemini unavailable — deterministic fallback used (%s: %s)",
                type(exc).__name__, exc,
            )
            return self._fallback_business_understanding(req)

    @staticmethod
    def _fallback_business_understanding(req: ResearchRequest) -> BusinessUnderstanding:
        """Continue discovery from supplied input only when Gemini is unavailable."""
        goal = re.sub(r"\s+", " ", req.business_goal).strip()
        sector = re.sub(r"\s+", " ", req.sector).strip()
        goal_terms = " ".join(re.findall(r"[A-Za-z0-9]+", goal)[:8])
        queries = [
            f'"{sector}" "{goal}" AI software',
            f'"{sector}" {goal_terms} software platform',
            f'"{goal}" AI solution pricing',
            f'"{goal}" customer case study software',
            f'"{sector}" workflow automation {goal_terms}',
            f'"{sector}" artificial intelligence {goal_terms} vendor',
        ]
        return BusinessUnderstanding(
            business_problem=goal,
            desired_outcomes=[goal],
            processes=[goal],
            capabilities=[],
            kpis=[],
            search_queries=list(dict.fromkeys(queries)),
        )

    async def _search_many(
        self,
        queries: list[str],
        num: int = 10,
    ):
        queries = [
            q.strip()
            for q in queries
            if q
            and q.strip()
        ]

        results = await asyncio.gather(
            *(
                self.serper.search(
                    q,
                    num=num,
                )
                for q in queries
            ),
            return_exceptions=True,
        )

        seen = set()
        merged = []
        failures = []

        for query, group in zip(
            queries,
            results,
        ):
            if isinstance(
                group,
                BaseException,
            ):
                failures.append(
                    f"{query}: {group}"
                )

                continue

            if not isinstance(
                group,
                (list, tuple),
            ):
                failures.append(
                    f"{query}: "
                    f"unexpected search response type "
                    f"{type(group).__name__}"
                )

                continue

            for r in group:
                if (
                    not r.url
                    or r.url in seen
                ):
                    continue

                seen.add(
                    r.url
                )

                merged.append(
                    r
                )

        if failures:
            logger.warning(
                "Serper failures: %s",
                " | ".join(
                    failures[:3]
                ),
            )

        logger.info(
            "Serper returned %s unique results for %s queries",
            len(merged),
            len(queries),
        )

        return merged

    @staticmethod
    def _canonical_search_url(url: str) -> str:
        """Canonical key for cross-provider duplicate suppression."""
        try:
            parts = urlsplit((url or "").strip())
            if not parts.scheme or not parts.netloc:
                return ""
            params = [
                (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                if not key.lower().startswith("utm_") and key.lower() not in {"gclid", "fbclid"}
            ]
            host = parts.netloc.lower().removeprefix("www.")
            path = parts.path.rstrip("/") or "/"
            return urlunsplit((parts.scheme.lower(), host, path, urlencode(params, doseq=True), "")).lower()
        except ValueError:
            return ""

    def _merge_search_results(self, *groups: list[SearchResult]) -> list[SearchResult]:
        """Merge providers by canonical publisher URL, never by Bing output text."""
        merged: list[SearchResult] = []
        seen: set[str] = set()
        for group in groups:
            for hit in group:
                key = self._canonical_search_url(hit.url)
                if not key or key in seen:
                    continue
                seen.add(key)
                hit.domain = hit.domain or registrable(hit.url)
                merged.append(hit)
        return merged

    async def _customer_search_many(
        self,
        queries: list[str],
        num: int = 10,
    ) -> list[SearchResult]:
        """Discover customer evidence with Serper plus optional Bing grounding.

        Both sources are candidates only. Publisher URLs continue through strict
        entity validation and Jina extraction before adoption can be verified.
        """
        queries = [self.serper.normalize_search_query(q) for q in queries]
        queries = list(dict.fromkeys(q for q in queries if q))
        serper_task = self._search_many(queries, num=num)
        bing_task = asyncio.gather(
            *(self.bing.search(query, num=min(num, settings.bing_search_result_count)) for query in queries),
            return_exceptions=True,
        ) if self.bing.configured else None

        serper_hits = await serper_task
        bing_hits: list[SearchResult] = []
        if bing_task is not None:
            for group in await bing_task:
                if isinstance(group, BaseException):
                    logger.warning("[CUSTOMER SEARCH] Bing grounding query failed: %s", group)
                elif isinstance(group, list):
                    bing_hits.extend(group)

        combined = self._merge_search_results(serper_hits, bing_hits)
        logger.info("[CUSTOMER SEARCH] Serper results: %s", len(serper_hits))
        logger.info("[CUSTOMER SEARCH] Bing results: %s", len(bing_hits))
        logger.info("[CUSTOMER SEARCH] Combined unique results: %s", len(combined))
        return combined

    async def _resolve_vendor_url(
        self,
        seed: CandidateSeed,
    ) -> CandidateSeed | None:
        if (
            seed.vendor_url
            and is_vendor_candidate(
                seed.vendor_url
            )
        ):
            return seed

        hits = await self._search_many(
            [
                f'"{seed.product}" '
                f'"{seed.vendor}" '
                f"official software"
            ],
            num=5,
        )

        for h in hits:
            if is_vendor_candidate(
                h.url
            ):
                return CandidateSeed(
                    product=seed.product,
                    vendor=seed.vendor,
                    vendor_url=h.url,
                    why_relevant=seed.why_relevant,
                )

        return None

    @staticmethod
    def _goal_concepts(req: ResearchRequest | None) -> set[str]:
        """Deterministic capability vocabulary derived from an outcome, not a sector."""
        goal = (req.business_goal if req else "").lower()
        concepts = set(re.findall(r"[a-z0-9]{4,}", goal))
        concepts -= {"with", "that", "from", "this", "your", "business", "reduce", "improve", "customer", "customers", "time", "times", "waiting"}
        mappings = (
            (("wait", "queue", "checkout", "line"), {"queue", "queuing", "customer flow", "line busting", "checkout", "self service", "pos", "throughput", "queue analytics"}),
            (("process", "processing", "workflow"), {"workflow", "automation", "orchestration", "processing", "productivity"}),
            (("cost", "labour", "labor", "efficiency"), {"automation", "workforce", "optimisation", "optimization", "productivity", "scheduling"}),
            (("sales", "conversion", "revenue"), {"conversion", "customer experience", "personalisation", "personalization", "analytics"}),
        )
        for signals, additions in mappings:
            if any(signal in goal for signal in signals):
                concepts.update(additions)
        return concepts

    @staticmethod
    def _is_obvious_nonproduct_result(hit: SearchResult) -> bool:
        url = (hit.url or "").lower()
        title = (hit.title or "").lower()
        blocked_domains = {"scribd.com", "reddit.com", "youtube.com", "facebook.com", "linkedin.com", "arxiv.org"}
        domain = registrable(hit.url).lower()
        return (
            not hit.url or not hit.title or domain in blocked_domains
            or url.endswith(".pdf") or "/pdf/" in url
            or any(part in url for part in ("/blog/", "/news/", "/article", "/guide", "/resources/", "/tutorial", "/posts/", "/case-study", "/customer-stor"))
            or any(term in title for term in ("top ", "best ", "how ", "what is ", "the rise of", "future of", "state of", "introduction to", "guide", "tutorial", "market report", "conference", "webinar", "case study", "person detection", "computer vision"))
        )

    @staticmethod
    def _candidate_vendor_from_hit(hit: SearchResult) -> str:
        title = (hit.title or "").strip()
        for separator in (" | ", " – ", " - ", " — "):
            if separator in title:
                left, tail = title.rsplit(separator, 1)
                left, tail = left.strip(), tail.strip()
                if 2 <= len(tail) <= 70 and not re.search(r"\b(software|platform|system|solution|retail)\b", tail, re.I):
                    return tail
                if 2 <= len(left) <= 50 and not re.search(r"\b(software|platform|system|solution|retail|queue|management)\b", left, re.I):
                    return left
        domain = registrable(hit.url)
        return domain.split(".")[0].replace("-", " ").title() if domain else ""

    async def _resolve_commercial_identity(self, hit: SearchResult, req: ResearchRequest) -> CandidateSeed | None:
        """Turn one commercial clue into an official canonical vendor candidate."""
        if self._is_obvious_nonproduct_result(hit):
            return None
        title, snippet = self._plain(hit.title, 160), self._plain(hit.snippet, 300)
        corpus = f"{title} {snippet}".lower()
        commercial = ("software", "platform", "system", "solution", "product", "pricing", "demo", "saas", "pos", "automation")
        concepts = self._goal_concepts(req)
        if not any(term in corpus for term in commercial) or (concepts and not any(term in corpus for term in concepts)):
            return None
        candidate_vendor = self._candidate_vendor_from_hit(hit)
        logger.info("[IDENTITY] original_title=%s candidate_vendor=%s resolution_attempted=true", title, candidate_vendor)
        # An official clue is already the strongest identity proof.  Third-party
        # clues get exactly one bounded official-domain search.
        official = hit if is_vendor_candidate(hit.url) else None
        hits = [official] if official else []
        if not official:
            queries = [
                f'"{candidate_vendor}" software',
                f'"{candidate_vendor}" ' + " ".join(sorted(concepts)[:3]),
                f'"{candidate_vendor}" product',
            ]
            hits.extend(await self._search_many(queries, num=5))
        for resolved in hits:
            if not resolved or not is_vendor_candidate(resolved.url) or self._is_obvious_nonproduct_result(resolved):
                continue
            domain = registrable(resolved.url)
            vendor = self._candidate_vendor_from_hit(resolved) or candidate_vendor
            # A category/solution page is a real commercial offering; vendor is
            # the conservative canonical product until validation reads it.
            product = vendor
            logger.info("[IDENTITY] official_domain=%s canonical_product=%s canonical_vendor=%s resolved=true reason=official commercial offering", domain, product, vendor)
            return CandidateSeed(product=product, vendor=vendor, vendor_url=resolved.url, why_relevant=snippet)
        logger.info("[IDENTITY] official_domain= canonical_product= canonical_vendor= resolved=false reason=no official commercial identity")
        return None

    def _canonicalise_candidate_seeds(self, seeds: list[CandidateSeed], limit: int) -> list[CandidateSeed]:
        """Deduplicate source mentions, while preserving distinct vendor products."""
        out, seen = [], set()
        for seed in seeds:
            domain = registrable(seed.vendor_url).lower()
            key = (domain or self._normalise_entity_text(seed.vendor), self._normalise_entity_text(seed.product))
            if not domain or not key[1] or key in seen:
                continue
            seen.add(key)
            out.append(seed)
            if len(out) >= limit:
                break
        return out

    def _fallback_candidate_seeds(
        self,
        results: list[SearchResult],
        limit: int,
        req: ResearchRequest | None = None,
    ) -> list[CandidateSeed]:
        """
        Deterministic fallback when Gemini quota is unavailable.

        Search/review/editorial sources may help discover products,
        but they must never become the product's vendor_url.

        Only plausible official commercial vendor domains are
        returned as CandidateSeed vendor URLs.
        """

        out = []
        seen_identities: set[tuple[str, str]] = set()

        non_vendor_domains = {
            "reddit.com",
            "youtube.com",
            "g2.com",
            "capterra.com",
            "trustpilot.com",
            "peerspot.com",
            "gartner.com",
            "getapp.com",
            "softwareadvice.com",
            "wikipedia.org",
            "forbes.com",
            "medium.com",
            "linkedin.com",
            "facebook.com",
            "scribd.com",
        }

        content_path_terms = (
            "/blog/", "/news/", "/article", "/articles/", "/glossary/",
            "/guide", "/resources/", "/tutorial", "/posts/", "/top-",
            "/best-", "/comparison/", "/case-study", "/customer-stor",
        )
        non_product_title_terms = (
            "top ", "best ", "how ", "what is ", "monitor and ",
            "person detection", "computer vision", "guide", "tutorial",
            "providers", "comparison", "case study", "customer story",
            "the rise of", "future of", "state of", "introduction to",
        )
        commercial_terms = (
            "software", "platform", "solution", "pricing", "request demo",
            "book demo", "enterprise", "free trial", "features", "integrations",
            "customers", "sign up", "login", "system", "pos", "checkout",
            "queue management", "customer flow", "automation",
        )
        goal_terms = self._goal_concepts(req)

        for hit in results:
            if not hit.url:
                continue

            domain = registrable(hit.url)

            if not domain:
                continue

            # Review/editorial/community sites remain available to the wider
            # research pipeline, but they must not be mistaken for vendors.
            if domain in non_vendor_domains:
                continue

            if not is_vendor_candidate(hit.url):
                continue

            title = self._plain(hit.title, 160)
            snippet = self._plain(hit.snippet, 300)

            if not title:
                continue

            low_url = hit.url.lower()
            low_title = title.lower()
            corpus = f"{title} {snippet}".lower()
            if self._is_obvious_nonproduct_result(hit):
                logger.info("[DISCOVERY:FALLBACK] rejected document source: %s", hit.url)
                continue
            if any(term in low_url for term in content_path_terms):
                logger.info("[DISCOVERY:FALLBACK] rejected non-product page: %s", hit.url)
                continue
            if any(low_title.startswith(term) or term in low_title for term in non_product_title_terms):
                logger.info("[DISCOVERY:FALLBACK] rejected non-product title: %s", title)
                continue
            if not any(term in corpus or term in low_url for term in commercial_terms):
                logger.info("[DISCOVERY:FALLBACK] rejected weak commercial identity: %s", title)
                continue
            if goal_terms and not any(term in corpus or term.rstrip("s") in corpus for term in goal_terms):
                logger.info("[DISCOVERY:FALLBACK] rejected weak goal relevance: %s", title)
                continue

            product = title

            for separator in (
                " | ",
                " - ",
                " — ",
                ": ",
            ):
                if separator in product:
                    product = product.split(separator)[0].strip()

            if len(product) < 2:
                continue

            vendor = (
                domain
                .split(".")[0]
                .replace("-", " ")
                .title()
            )
            # A root/product vendor page may identify a product by the vendor
            # brand. Never use a descriptive article title as that identity.
            vendor_token = re.sub(r"[^a-z0-9]", "", vendor.lower())
            product_token = re.sub(r"[^a-z0-9]", "", product.lower())
            generic_product_terms = {"retail", "queue", "management", "system", "software", "platform", "solution", "solutions", "checkout", "customer", "flow", "store", "pickup"}
            product_words = set(re.findall(r"[a-z0-9]+", product.lower()))
            if vendor_token and vendor_token in product_token:
                product = vendor
            elif product_words and product_words <= generic_product_terms:
                # This is an official commercial category/solution page.  The
                # vendor is the safe canonical identity until validation reads
                # the official product offering.
                product = vendor
            elif len(product.split()) > 5:
                logger.info("[DISCOVERY:FALLBACK] rejected unresolved product identity: %s", title)
                continue

            identity = (product.casefold(), domain)
            if identity in seen_identities:
                continue
            seen_identities.add(identity)

            out.append(
                CandidateSeed(
                    product=product,
                    vendor=vendor,
                    vendor_url=hit.url,
                    why_relevant=snippet,
                )
            )

            if len(out) >= limit:
                break

        return out

    @staticmethod
    def _discovery_expansion_queries(req: ResearchRequest) -> list[str]:
        """Bounded product-intent queries from deterministic outcome concepts."""
        sector = re.sub(r"\s+", " ", req.sector or "").strip()
        concepts = sorted(ResearchService._goal_concepts(req))[:8]
        queries = []
        for concept in concepts[:4]:
            queries.extend((
                f'"{concept}" software', f'"{concept}" platform',
                f'"{sector}" "{concept}" software', f'"{concept}" pricing vendor',
            ))
        return list(dict.fromkeys(q for q in queries if q.strip()))[:12]

    async def _discover_candidates(
        self,
        req: ResearchRequest,
        understanding: BusinessUnderstanding,
    ):
        logger.info(
            "[1/7] Commercial product discovery started"
        )

        results = await self._search_many(
            understanding.search_queries[:10],
            num=10,
        )

        if not results:
            raise RuntimeError(
                "Serper returned no search results. "
                "Check SERPER_API_KEY, quota, and internet access."
            )

        obvious_rejected = sum(self._is_obvious_nonproduct_result(hit) for hit in results)
        concepts = self._goal_concepts(req)
        commercial_clues = sum(
            not self._is_obvious_nonproduct_result(hit)
            and any(term in f"{hit.title} {hit.snippet}".lower() for term in ("software", "platform", "system", "solution", "product", "pricing", "demo", "saas", "pos", "automation"))
            and (not concepts or any(term in f"{hit.title} {hit.snippet}".lower() for term in concepts))
            for hit in results
        )
        logger.info("[DISCOVERY] search_results=%s obvious_nonproducts_rejected=%s commercial_clues=%s", len(results), obvious_rejected, commercial_clues)

        compact = [
            {
                "title": r.title,
                "url": r.url,
                "snippet": r.snippet,
            }
            for r in results[:80]
        ]

        prompt = f"""
Identify distinct real commercial software/AI products
from these live search results.

Problem:
{getattr(understanding, "business_problem", req.business_goal)}

Sector:
{req.sector}

Goal:
{req.business_goal}

Search results:
{json.dumps(compact)[:48000]}

Rules:

- Return up to {settings.max_candidates} products.
- Prefer products that directly solve the stated business problem.
- vendor_url must be an official vendor/product URL when identifiable.
- Never use a review site, publisher, consultancy, market report,
  or academic paper as vendor_url.
- Global vendors are allowed.
- Organisation country does not restrict vendor headquarters.
- Never invent a product.
"""

        try:
            seeds = await self.gemini.structured(
                prompt,
                CandidateSeeds,
            )

        except Exception as exc:
            message = str(
                exc
            ).lower()

            recoverable = (
                "429" in message
                or "resource_exhausted" in message
                or "quota" in message
                or "503" in message
                or "unavailable" in message
                or "timeout" in message
                or "connect" in message
                or "readerror" in message
                or "dns" in message
            )

            if (
                recoverable
                or isinstance(exc, (GeminiUnavailableError, asyncio.TimeoutError, TimeoutError))
            ):
                logger.warning(
                    "Gemini unavailable during product discovery. "
                    "Using deterministic Serper fallback."
                )

                fallback = self._fallback_candidate_seeds(
                    results,
                    settings.max_candidates,
                    req,
                )

                # Search results are clues, not product identities. Resolve
                # strong commercial clues once before discarding them.
                resolved_clues = await asyncio.gather(
                    *(self._resolve_commercial_identity(hit, req) for hit in results[:50]),
                    return_exceptions=True,
                )
                fallback.extend(item for item in resolved_clues if isinstance(item, CandidateSeed))
                fallback = self._canonicalise_candidate_seeds(fallback, settings.max_candidates)
                logger.info("[DISCOVERY] identity_resolution_attempts=%s identities_resolved=%s", commercial_clues, sum(isinstance(item, CandidateSeed) for item in resolved_clues))

                # Gemini may normally turn broad discovery results into product
                # identities.  When it is unavailable, make one strictly
                # commercial, goal-derived Serper expansion before accepting a
                # small result set.  The same strict fallback filter applies.
                minimum_defensible = min(3, settings.max_candidates)
                if len(fallback) < minimum_defensible:
                    expansion_queries = self._discovery_expansion_queries(req)
                    logger.info(
                        "[DISCOVERY:FALLBACK] expanding deterministic vendor-intent search (%s queries)",
                        len(expansion_queries),
                    )
                    expansion_results = await self._search_many(expansion_queries, num=8)
                    results = self._merge_search_results(results, expansion_results)
                    fallback = self._fallback_candidate_seeds(
                        results,
                        settings.max_candidates,
                        req,
                    )
                    resolved_clues = await asyncio.gather(
                        *(self._resolve_commercial_identity(hit, req) for hit in expansion_results[:50]),
                        return_exceptions=True,
                    )
                    fallback.extend(item for item in resolved_clues if isinstance(item, CandidateSeed))
                    fallback = self._canonicalise_candidate_seeds(fallback, settings.max_candidates)

                seeds = CandidateSeeds(
                    candidates=fallback
                )
            else:
                raise

        logger.info(
            "[DISCOVERY] Candidate seeds produced: %s",
            len(seeds.candidates),
        )
        logger.info("[DISCOVERY] canonical_candidates=%s", len(seeds.candidates))

        for i, seed in enumerate(seeds.candidates, 1):
            logger.info(
                "[DISCOVERY] Seed %s: product=%s | vendor=%s | url=%s",
                i,
                seed.product,
                seed.vendor,
                seed.vendor_url,
            )

        resolved = await asyncio.gather(
            *(
                self._resolve_vendor_url(c)
                for c in seeds.candidates
            ),
            return_exceptions=True,
        )

        valid_resolved = [
            x
            for x in resolved
            if isinstance(x, CandidateSeed)
        ]

        logger.info(
            "[DISCOVERY] Vendor URLs successfully resolved: %s/%s",
            len(valid_resolved),
            len(seeds.candidates),
        )

        out = []
        identities = set()

        for c in resolved:
            if not isinstance(
                c,
                CandidateSeed,
            ):
                continue

            d = registrable(
                c.vendor_url
            )

            identity = (d, self._normalise_entity_text(c.product))
            if not d or identity in identities:
                continue
            identities.add(identity)

            out.append(
                c
            )

        logger.info(
            "[1/7] %s product candidates resolved to vendor domains",
            len(out),
        )

        if not out:
            raise RuntimeError(
                "Search results were found, "
                "but no commercial vendor domains could be validated."
            )

        return (
            out[:settings.max_candidates],
            results,
        )

    async def _read_pages(
        self,
        urls: list[str],
        limit: int,
    ):
        if not hasattr(self, "_page_cache"):
            self._page_cache = {}

        uniq = list(
            dict.fromkeys(
                u.strip()
                for u in urls
                if u and u.strip()
            )
        )[:limit]

        results = []
        to_fetch = []
        for u in uniq:
            canonical_u = u.rstrip("/")
            if canonical_u in self._page_cache:
                results.append(self._page_cache[canonical_u])
            else:
                to_fetch.append(u)

        if to_fetch:
            rows = await asyncio.gather(
                *(self.jina.read(u) for u in to_fetch),
                return_exceptions=True,
            )
            for u, x in zip(to_fetch, rows):
                if isinstance(x, dict) and x.get("content"):
                    canonical_u = u.rstrip("/")
                    self._page_cache[canonical_u] = x
                    results.append(x)

        return results

    @staticmethod
    def _outcome_search_terms(req: ResearchRequest) -> list[str]:
        """Create goal-led outcome terms without assuming a sector."""
        goal = (req.business_goal or "").lower()
        terms = ["case study results", "customer success measurable results", "ROI", "saved hours", "reduced costs"]
        mappings = (
            (("wait", "queue", "checkout"), ["waiting time reduction", "throughput improvement", "labour efficiency"]),
            (("process", "processing"), ["processing time reduction", "faster processing", "productivity improvement"]),
            (("conversion", "sales", "revenue"), ["conversion increase", "revenue increase"]),
            (("cost", "labour", "labor"), ["cost savings", "labour savings", "operational results"]),
        )
        for signals, additions in mappings:
            if any(signal in goal for signal in signals):
                terms.extend(additions)
        return list(dict.fromkeys(terms))[:8]

    def _deterministic_customer_impacts(
        self, candidate: ProductCandidate, pages: list[dict], vendor_domain: str
    ) -> list[dict]:
        """Extract unambiguous numeric outcomes from read customer/case-study pages.

        This intentionally has a small grammar: it is a resilience path for explicit
        claims, not an attempt to infer business meaning when the model is unavailable.
        """
        impacts, seen = [], set()
        money = r"(?:[£$€]|GBP\s*|USD\s*|EUR\s*)[\d,]+(?:\.\d+)?"
        patterns = (
            (rf"(?P<metric>[A-Za-z ][A-Za-z -]{{2,50}}?)\s+(?P<direction>reduced|decreased|cut)\s+(?:by\s+)?(?P<value>[\d.]+)\s*(?P<unit>%|percent)", "operational"),
            (rf"(?P<direction>reduced|decreased|cut)\s+(?P<metric>[A-Za-z ][A-Za-z -]{{2,50}}?)\s+(?:by\s+)?(?P<value>[\d.]+)\s*(?P<unit>%|percent)", "operational"),
            (rf"(?P<direction>saved|generated)\s+(?P<value>{money}|[\d,]+(?:\.\d+)?\s*(?:hours?|minutes?|days?))", "financial"),
            (rf"(?P<metric>[A-Za-z ][A-Za-z -]{{2,50}}?)\s+(?P<direction>increased|improved)\s+(?:by\s+)?(?P<value>[\d.]+)\s*(?P<unit>%|percent)", "operational"),
            (r"(?P<before>[\d.]+)\s*(?P<unit>minutes?|mins?|hours?)\s*(?:to|→|->)\s*(?P<after>[\d.]+)\s*(?P=unit)", "operational"),
            (r"(?P<value>[\d.]+)\s*x\s+(?P<direction>faster)", "operational"),
            (r"ROI\s+(?:of|was)\s*(?P<value>[\d.]+)\s*(?P<unit>%|percent)", "financial"),
            (r"(?P<value>[\d.]+)\s*(?P<unit>%|percent)\s*ROI", "financial"),
            (r"(?P<metric>[A-Za-z ][A-Za-z -]{2,60}?)\s+(?P<direction>reduced|decreased|improved|increased)\s+(?:by\s+)?(?P<value>[\d.]+)\s*(?P<unit>%|percent)", "operational"),
            (rf"(?P<value>{money})\s+(?:in\s+)?(?P<metric>annual\s+(?:cost\s+)?savings?|savings?)", "financial"),
            (r"(?P<value>[\d.]+)\s*[- ]?month\s+(?P<metric>payback)", "financial"),
        )
        product_tokens = self._meaningful_tokens(candidate.product)
        for page in pages:
            url, title, text = page.get("url", ""), page.get("title", ""), page.get("content", "")
            if not text or not url:
                continue
            corpus = f"{title} {text}"
            # A non-vendor page must name the actual product; vendor case-study
            # pages are trusted for product identity but still need a named customer.
            if registrable(url) != vendor_domain and not all(t in corpus.lower() for t in product_tokens):
                continue
            slug = re.search(r"(?:case-stud(?:y|ies)|customers?|customer-stories)/([^/?#]+)", url.lower())
            name_match = re.search(r"(?:case study|customer story)\s*[:\-–]\s*([A-Z][A-Za-z0-9& .'-]{2,70})", title)
            customer = (name_match.group(1).strip() if name_match else (re.sub(r"[-_]+", " ", slug.group(1)).title() if slug else ""))
            if customer.lower() in {"case study", "customer story", candidate.product.lower()}:
                continue
            # A named company on a page is not enough. Require explicit use,
            # implementation or deployment language alongside the product.
            relation_text = corpus.lower()
            customer_tokens = self._meaningful_tokens(customer)
            relationship = re.search(r"\b(?:uses?|used|implemented|deployed|adopted|rolled\s+out)\b", relation_text)
            if registrable(url) != vendor_domain and (not relationship or not all(token in relation_text for token in customer_tokens | product_tokens)):
                continue
            for pattern, classification in patterns:
                for match in re.finditer(pattern, text, re.I):
                    claim = self._plain(text[max(0, match.start()-130):match.end()+130], 420)
                    groups = match.groupdict()
                    raw_value = groups.get("value", "")
                    numeric = re.search(r"[\d.]+", raw_value)
                    before = float(groups["before"]) if groups.get("before") else None
                    after = float(groups["after"]) if groups.get("after") else None
                    value = float(numeric.group()) if numeric else (round((before-after) / before * 100, 2) if before and after else None)
                    currency_match = re.search(r"[£$€]|GBP|USD|EUR", raw_value, re.I)
                    duration_match = re.search(r"hours?|minutes?|days?", raw_value, re.I)
                    unit = groups.get("unit") or ("%" if before is not None else ("currency" if currency_match else (duration_match.group().lower() if duration_match else "")))
                    if value is None:
                        continue
                    key = (url.rstrip("/"), customer.casefold(), str(groups.get("metric") or groups.get("direction") or ""), value, unit)
                    if key in seen:
                        continue
                    seen.add(key)
                    impacts.append({"customer": customer, "product": candidate.product, "metric": (groups.get("metric") or "Customer outcome").strip(), "impact_value": value, "impact_unit": unit, "before_value": before, "after_value": after, "direction": groups.get("direction") or ("reduced" if before else ""), "classification": classification, "claim": claim, "source_url": url, "source_domain": registrable(url), "source_type": "vendor_case_study" if registrable(url) == vendor_domain else "independent_article", "source_quality": "medium", "confidence": 0.82, "extraction_method": "deterministic_page_pattern"})
        return impacts

    def _deterministic_customer_references(
        self, candidate: ProductCandidate, pages: list[dict], vendor_domain: str
    ) -> list[dict]:
        """Retain only page-level, explicit customer/product relationships."""
        customers, seen = [], set()
        relationship_pattern = re.compile(
            r"\b(?:uses?|used|implemented|deployed|adopted|rolled\s+out)\b",
            re.I,
        )
        for page in pages:
            url = str(page.get("url") or "")
            title = str(page.get("title") or "")
            text = str(page.get("content") or "")
            if not url or not text:
                continue
            corpus = f"{title} {text}"
            source_domain = registrable(url)
            if source_domain != vendor_domain and not self._entity_match(
                candidate, url=url, title=title, text=text, strict=True
            ):
                continue
            slug = re.search(
                r"(?:case-stud(?:y|ies)|customers?|customer-stories)/([^/?#]+)",
                url.lower(),
            )
            name_match = re.search(
                r"(?:case study|customer story)\s*[:\-–]\s*([A-Z][A-Za-z0-9& .'-]{2,70})",
                title,
            )
            customer = (
                name_match.group(1).strip()
                if name_match
                else (re.sub(r"[-_]+", " ", slug.group(1)).title() if slug else "")
            )
            customer_tokens = self._meaningful_tokens(customer)
            corpus_lower = corpus.lower()
            if (
                not customer_tokens
                or customer.lower() in {"case study", "customer story", candidate.product.lower()}
                or not all(token in corpus_lower for token in customer_tokens)
                or not relationship_pattern.search(corpus)
            ):
                continue
            key = (customer.casefold(), url.rstrip("/"))
            if key in seen:
                continue
            seen.add(key)
            customers.append({
                "customer": customer,
                "product": candidate.product,
                "source_url": url,
                "source_title": title,
                "source_domain": source_domain,
                "source_type": "vendor_case_study" if source_domain == vendor_domain else "independent_article",
                "evidence_text": self._plain(text, 400),
                "confidence": 0.75,
                "extraction_method": "deterministic_page_relationship",
            })
        return customers

    def _is_genuine_commercial_candidate(
        self,
        seed: CandidateSeed,
        source: str = "",
        req: ResearchRequest | None = None,
    ) -> tuple[bool, str, float]:
        """
        Verify whether a discovered seed is a genuine commercial product.

        Enforces genuine-product requirements:
        - Identifiable commercial product name and vendor
        - Non-article, non-editorial, non-social vendor URL
        - Commercial terminology presence (platform, software, solution, pricing, etc.)
        - Business goal relevance
        - Rejects articles, listicles, blog posts, Facebook/Reddit/social posts,
          glossaries, research papers, tutorials, generic technology concepts.

        Returns (is_genuine, reason, evidence_score).
        """
        product = (seed.product or "").strip()
        vendor = (seed.vendor or "").strip()
        url = (seed.vendor_url or "").strip().lower()

        if len(product) < 2 or len(vendor) < 2:
            return False, "product or vendor name too short", 0.0

        domain = registrable(seed.vendor_url).lower()
        if not domain or not is_vendor_candidate(seed.vendor_url):
            return False, f"non-vendor domain: {domain}", 0.0

        blocked_social_editorial = {
            "facebook.com", "reddit.com", "youtube.com", "linkedin.com",
            "medium.com", "wikipedia.org", "forbes.com", "quora.com",
            "twitter.com", "x.com", "instagram.com", "tiktok.com",
            "github.com", "arxiv.org", "sciencedirect.com",
        }
        if any(d == domain or domain.endswith("." + d) for d in blocked_social_editorial):
            return False, f"editorial/social domain: {domain}", 0.0

        content_path_terms = (
            "/blog/", "/news/", "/article", "/articles/", "/glossary/",
            "/guide", "/resources/", "/tutorial", "/posts/", "/top-",
            "/best-", "/comparison/", "/case-study", "/customer-stor",
            "/post/", "/stories/",
        )
        if any(term in url for term in content_path_terms):
            return False, f"content path in vendor url: {seed.vendor_url}", 0.0

        low_product = product.lower()
        non_product_title_terms = (
            "top ", "best ", "how ", "what is ", "guide", "tutorial",
            "providers", "comparison", "list of", "overview of",
            "10 best", "10 top", "5 best", "person detection",
            "computer vision", "queue management", "artificial intelligence",
        )
        if any(low_product.startswith(term) for term in non_product_title_terms):
            return False, f"non-product title prefix: {product}", 0.0

        generic_concepts = {
            "queue management", "person detection", "computer vision",
            "video analytics", "ai queue management", "waiting time reduction",
            "virtual queue", "smart queue", "customer flow management",
        }
        if low_product in generic_concepts:
            return False, f"generic technology concept without commercial identity: {product}", 0.0

        # A title composed only of category/editorial vocabulary is not a
        # product identity, even when hosted by a commercial vendor website.
        editorial_prefixes = ("the rise of", "future of", "state of", "introduction to", "what is")
        generic_identity_tokens = {"retail", "automation", "checkout", "free", "technology", "software", "solutions", "platform"}
        product_tokens_for_identity = set(self._meaningful_tokens(product))
        if low_product.startswith(editorial_prefixes) or (product_tokens_for_identity and product_tokens_for_identity <= generic_identity_tokens):
            return False, f"editorial/category title without identifiable product identity: {product}", 0.0

        source_lower = (source or "").lower()
        commercial_terms = (
            "software", "platform", "solution", "solutions", "pricing",
            "request demo", "book demo", "enterprise", "free trial", "features",
            "integrations", "customers", "sign up", "login", "cloud", "saas",
            "product", "api", "dashboard", "subscription",
        )

        has_commercial_signals = any(term in source_lower or term in url for term in commercial_terms)
        if not has_commercial_signals:
            return False, "no commercial terminology found in source or url", 0.0

        if req and req.business_goal:
            goal_tokens = {
                token for token in re.findall(r"[a-z0-9]{4,}", req.business_goal.lower())
                if token not in {"with", "that", "from", "this", "your", "business", "reduce", "improve"}
            }
            goal_tokens.update(self._goal_concepts(req))
            if goal_tokens:
                relevance = any(
                    tok in source_lower or tok.rstrip("s") in source_lower or
                    tok in (seed.why_relevant or "").lower()
                    for tok in goal_tokens
                )
                if not relevance:
                    return False, "no business goal relevance detected in evidence", 0.0

        # Calculate evidence score from real signals (not arbitrary flat value)
        score = 50.0
        if len(source) >= 8000:
            score += 15.0
        elif len(source) >= 3000:
            score += 10.0
        elif len(source) >= 1000:
            score += 5.0

        commercial_matches = sum(term in source_lower for term in commercial_terms)
        if commercial_matches >= 4:
            score += 5.0

        product_tokens = self._meaningful_tokens(seed.product)
        if any(t in source_lower for t in product_tokens):
            score += 5.0

        return True, "valid commercial product", min(80.0, score)

    async def _validate_products_batch(
        self,
        req,
        understanding,
        seeds: list[CandidateSeed],
    ):
        bundles = []

        for seed in seeds:
            domain = registrable(seed.vendor_url)

            hits = await self._search_many(
                [
                    f'site:{domain} "{seed.product}" features customers case study {req.sector}'
                ],
                num=10,
            )

            vendor_urls = [seed.vendor_url] + [
                h.url for h in hits if registrable(h.url) == domain
            ][:5]

            pages = await self._read_pages(vendor_urls, 5)

            if pages:
                source = "\n".join(
                    f'URL: {p["url"]}\nTITLE: {p.get("title", "")}\nCONTENT: {self._plain(p.get("content", ""), 6000)}'
                    for p in pages
                )
            else:
                source = "\n".join(
                    f"URL: {h.url}\nTITLE: {h.title}\nSNIPPET: {h.snippet}"
                    for h in hits[:8]
                )

            bundles.append(
                {
                    "product": seed.product,
                    "vendor": seed.vendor,
                    "vendor_url": seed.vendor_url,
                    "source": source[:26000],
                }
            )

        prompt = f"""
Validate all candidate commercial products using only the supplied evidence.

Sector:
{req.sector}

Business goal:
{req.business_goal}

Required capabilities:
{understanding.capabilities}

For every candidate:
- Score 0-100 for goal fit.
- Score 0-100 for sector fit.
- Score 0-100 for evidence quality.
- Score 0-100 for adoption evidence.
- Score 0-100 for current product momentum.
- Score 0-100 for implementation feasibility.

Keep only genuine commercial products materially relevant to the stated business goal.
Evidence items must retain real source URLs.
Never invent customers, metrics, costs, capabilities, or URLs.
If evidence is weak, score conservatively.

CANDIDATES:
{json.dumps(bundles)[:120000]}
"""

        gemini_analyses: dict[str, ProductAnalysis] = {}
        gemini_succeeded = False

        try:
            analysed = await self.gemini.structured(
                prompt,
                BatchProductAnalyses,
            )
            gemini_succeeded = True
            logger.info(
                "[VALIDATION] Gemini returned %s/%s candidates",
                len(analysed.products),
                len(seeds),
            )
            for product in analysed.products:
                logger.info(
                    "[VALIDATION] %s | commercial=%s | relevant=%s | goal=%.1f | sector=%.1f | evidence=%.1f",
                    product.product,
                    product.is_commercial_product,
                    product.is_relevant,
                    product.goal_fit,
                    product.sector_fit,
                    product.evidence_score,
                )
                if product.is_commercial_product and product.is_relevant:
                    gemini_analyses[product.product.lower().strip()] = product

        except Exception as exc:
            message = str(exc).lower()
            recoverable = (
                "429" in message
                or "resource_exhausted" in message
                or "quota" in message
                or "rate-limit" in message
                or "rate limit" in message
                or "503" in message
                or "500" in message
                or "502" in message
                or "504" in message
                or "5xx" in message
                or "unavailable" in message
                or "timeout" in message
                or "connect" in message
                or "readerror" in message
                or "validationerror" in message
            )
            if not recoverable and not isinstance(exc, GeminiUnavailableError):
                raise

            logger.warning(
                "[VALIDATION] Gemini unavailable (%s: %s). Using conservative deterministic validation fallback.",
                type(exc).__name__,
                exc,
            )

        # Pre-evaluate genuine commercial candidate status for all seeds
        genuine_candidates = []
        seed_evaluation = {}
        for seed, bundle in zip(seeds, bundles):
            is_genuine, reason, evidence_score = self._is_genuine_commercial_candidate(
                seed, bundle.get("source", ""), req
            )
            seed_evaluation[seed.vendor_url] = (is_genuine, reason, evidence_score)
            if is_genuine:
                genuine_candidates.append(seed)
            else:
                logger.info(
                    "[VALIDATION] REJECTED non-commercial seed: %s | %s | reason=%s",
                    seed.product,
                    seed.vendor,
                    reason,
                )

        out: list[ProductCandidate] = []
        retained_urls: set[str] = set()
        gemini_validated_count = 0
        deterministic_valid_count = 0

        # Step 1: Match and retain candidates validated by Gemini (1-to-1 matching with consumption)
        # Step 1: Match and retain candidates validated by Gemini
        if gemini_succeeded:
            gemini_analysis_items = list(gemini_analyses.items())
            claimed_analysis_keys: set[str] = set()

            for seed, bundle in zip(seeds, bundles):
                is_genuine, _, _ = seed_evaluation.get(seed.vendor_url, (False, "", 0.0))
                if not is_genuine:
                    continue

                seed_p_norm = self._normalise_entity_text(seed.product)
                seed_v_norm = self._normalise_entity_text(seed.vendor)
                seed_p_tokens = self._meaningful_tokens(seed.product)
                seed_v_tokens = self._meaningful_tokens(seed.vendor)
                seed_tokens = self._meaningful_tokens(seed.product)
                seed_domain = registrable(seed.vendor_url).lower()
                domain_core = self._normalise_entity_text(seed_domain.split(".")[0]) if seed_domain else ""

                best_analysis = None
                best_score = 0
                best_key = None

                for name_key, analysis in gemini_analysis_items:
                    if name_key in claimed_analysis_keys:
                        continue
                    analysis_p_norm = self._normalise_entity_text(analysis.product)
                    analysis_v_norm = self._normalise_entity_text(analysis.vendor)
                    analysis_p_tokens = self._meaningful_tokens(analysis.product)
                    analysis_v_tokens = self._meaningful_tokens(analysis.vendor)

                    # 1. MANDATORY Vendor / Domain Alignment:
                    # A validation result may map back to a discovery seed only when
                    # vendor/domain identity is sufficiently supported.
                    vendor_match = False
                    vendor_score = 0
                    if seed_v_norm and analysis_v_norm:
                        if seed_v_norm == analysis_v_norm:
                            vendor_match = True
                            vendor_score = 40
                        elif seed_v_norm in analysis_v_norm or analysis_v_norm in seed_v_norm:
                            vendor_match = True
                            vendor_score = 30
                    if not vendor_match and domain_core and len(domain_core) >= 3:
                        if domain_core in analysis_v_norm or domain_core in analysis_p_norm:
                            vendor_match = True
                            vendor_score = 35
                    if not vendor_match and seed_v_tokens and (seed_v_tokens & analysis_v_tokens or seed_v_tokens & analysis_p_tokens):
                        vendor_match = True
                        vendor_score = 25

                    if not vendor_match:
                        # Cannot map an analysis from a different vendor/domain to this seed!
                        continue

                    # 2. Product Name Compatibility:
                    score = vendor_score
                    if seed_p_norm == analysis_p_norm:
                        score += 50
                    elif (seed_p_norm and seed_p_norm in analysis_p_norm) or (analysis_p_norm and analysis_p_norm in seed_p_norm):
                        score += 30
                    elif seed_p_tokens and (seed_p_tokens & analysis_p_tokens):
                        score += 25
                    elif seed_v_norm and seed_v_norm in analysis_p_norm:
                        score += 20
                    elif domain_core and domain_core in analysis_p_norm:
                        score += 20

                    if score > best_score:
                        best_score = score
                        best_analysis = analysis
                        best_key = name_key

                if best_analysis and best_score >= 25 and best_key:
                    claimed_analysis_keys.add(best_key)
                    # Retain seed product identity as anchor so candidate names are never corrupted
                    resolved_product = seed.product
                    if best_analysis.product and (seed_p_norm in self._normalise_entity_text(best_analysis.product) or seed_v_norm in self._normalise_entity_text(best_analysis.product)):
                        resolved_product = best_analysis.product

                    out.append(
                        ProductCandidate(
                            product=resolved_product,
                            vendor=seed.vendor or best_analysis.vendor,
                            vendor_url=seed.vendor_url,
                            description=best_analysis.description or seed.why_relevant,
                            capabilities=best_analysis.capabilities,
                            sector_relevance=best_analysis.sector_relevance,
                            goal_relevance=best_analysis.goal_relevance,
                            evidence=best_analysis.evidence,
                            goal_fit=best_analysis.goal_fit,
                            sector_fit=best_analysis.sector_fit,
                            evidence_score=best_analysis.evidence_score,
                            adoption_score=best_analysis.adoption_score,
                            momentum_score=best_analysis.momentum_score,
                            implementation_score=best_analysis.implementation_score,
                        )
                    )
                    retained_urls.add(seed.vendor_url)
                    gemini_validated_count += 1
                    logger.info(
                        "[VALIDATION:MATCHED] Seed '%s' (%s) matched Gemini '%s' (%s) [score=%s]",
                        seed.product,
                        seed.vendor,
                        best_analysis.product,
                        best_analysis.vendor,
                        best_score,
                    )

        # Step 2: If fewer than 3 products retained and more genuine commercial
        # candidates exist, use deterministic validation to attempt to retain at least 3.
        target_retention = min(3, len(genuine_candidates))
        if len(out) < target_retention:
            for seed, bundle in zip(seeds, bundles):
                if seed.vendor_url in retained_urls:
                    continue
                is_genuine, reason, evidence_score = seed_evaluation.get(seed.vendor_url, (False, "", 0.0))
                if not is_genuine:
                    continue

                out.append(
                    ProductCandidate(
                        product=seed.product,
                        vendor=seed.vendor,
                        vendor_url=seed.vendor_url,
                        description=seed.why_relevant or "",
                        capabilities=[],
                        sector_relevance=(
                            "Preliminary fallback validation only; sector fit requires deep evidence confirmation."
                        ),
                        goal_relevance=(
                            seed.why_relevant
                            or "Discovered from searches for the stated business goal; goal fit requires deep evidence confirmation."
                        ),
                        goal_fit=55.0,
                        sector_fit=50.0,
                        evidence_score=evidence_score,
                        adoption_score=50.0,
                        momentum_score=50.0,
                        implementation_score=50.0,
                        evidence=[],
                    )
                )
                retained_urls.add(seed.vendor_url)
                deterministic_valid_count += 1
                logger.info(
                    "[VALIDATION:DETERMINISTIC] Retained genuine commercial candidate: %s | %s | evidence=%.1f",
                    seed.product,
                    seed.vendor,
                    evidence_score,
                )
                if len(out) >= 3:
                    break

        # Step 3: Canonical deduplication stage
        unique_out: list[ProductCandidate] = []
        seen_identities: set[tuple[str, str]] = set()
        seen_domains: set[str] = set()
        duplicates_removed = 0

        for cand in out:
            dom = registrable(cand.vendor_url).lower()
            p_norm = self._normalise_entity_text(cand.product)
            v_norm = self._normalise_entity_text(cand.vendor)
            identity_key = (dom or v_norm, p_norm)

            if identity_key in seen_identities:
                duplicates_removed += 1
                logger.info(
                    "[VALIDATION] duplicate matched result rejected: %s | %s (%s)",
                    cand.product,
                    cand.vendor,
                    dom,
                )
                continue

            if dom and dom in seen_domains:
                existing = next((c for c in unique_out if registrable(c.vendor_url).lower() == dom), None)
                if existing:
                    ex_p = self._normalise_entity_text(existing.product)
                    if ex_p == p_norm or ex_p in p_norm or p_norm in ex_p:
                        duplicates_removed += 1
                        logger.info(
                            "[VALIDATION] duplicate matched result rejected: %s | %s (%s) collides with %s",
                            cand.product,
                            cand.vendor,
                            dom,
                            existing.product,
                        )
                        continue

            seen_identities.add(identity_key)
            if dom:
                seen_domains.add(dom)
            unique_out.append(cand)

        out = unique_out
        logger.info("[VALIDATION] duplicates removed=%s", duplicates_removed)
        logger.info("[VALIDATION] unique validated candidates=%s", len(out))

        # Diagnostic logs as explicitly specified
        logger.info("[VALIDATION] discovered candidates=%s", len(seeds))
        logger.info("[VALIDATION] genuine commercial candidates=%s", len(genuine_candidates))
        logger.info("[VALIDATION] Gemini-validated=%s", gemini_validated_count)
        logger.info("[VALIDATION] deterministic-valid=%s", deterministic_valid_count)
        logger.info("[VALIDATION] retained=%s", len(out))
        logger.info("[VALIDATION] candidates=%s validated=%s rejected=%s", len(seeds), len(out), len(seeds) - len(genuine_candidates))
        logger.info("[VALIDATION] target minimum=3")
        if len(out) < 3:
            logger.info("[VALIDATION] only %s defensible products available; minimum not forced", len(out))

        for product in out:
            logger.info("[VALIDATION] KEPT: %s | %s", product.product, product.vendor)

        return out

    def _evidence_from_hits(
        self,
        hits: list[SearchResult],
        pages: list[dict],
        vendor_domain: str,
        target: int = 30,
    ):
        page_by_url = {
            p.get("url"): p
            for p in pages
        }

        rows = []

        for hit in hits:
            page = page_by_url.get(
                hit.url,
                {},
            )

            excerpt = self._plain(
                page.get("content")
                or hit.snippet,
                900,
            )

            if (
                not excerpt
                and not hit.title
            ):
                continue

            rows.append(
                EvidenceItem(
                    source_url=hit.url,
                    source_title=(
                        hit.title
                        or page.get(
                            "title",
                            "",
                        )
                    ),
                    evidence_type="source_record",
                    claim=self._plain(
                        hit.snippet
                        or hit.title,
                        420,
                    ),
                    supporting_text=excerpt,
                    source_quality=self._source_quality(
                        hit.url,
                        vendor_domain,
                    ),
                    confidence=(
                        0.72
                        if page
                        else 0.48
                    ),
                    search_provider=hit.search_provider,
                    domain=hit.domain or registrable(hit.url),
                    search_query=hit.query,
                )
            )

            if len(rows) >= target:
                break

        return rows

    @staticmethod
    def _normalise_entity_text(value: str) -> str:
        value = re.sub(
        r"[^a-z0-9]+",
        " ",
        str(value or "").lower(),
    )
        return re.sub(r"\s+", " ", value).strip()


    @staticmethod
    def _meaningful_tokens(value: str) -> set[str]:
        stop = {
            "ai", "the", "and", "for", "software", "system", "systems", "platform",
            "solution", "solutions", "management", "tool", "tools", "app", "apps",
            "suite", "service", "services", "digital", "smart", "analytics", "cloud",
            "queue", "queuing", "queues", "waiting", "line", "lines", "checkout",
            "retail", "store", "stores", "customer", "customers", "visitor", "visitors",
            "traffic", "people", "counter", "counters", "counting", "sensor", "sensors",
            "camera", "cameras", "flow", "journey", "virtual", "tracking", "monitor",
            "pos", "point", "sale", "hardware", "device", "devices", "intelligence",
            "ai",
            "the",
            "and",
            "for",
            "software",
            "system",
            "platform",
            "solution",
            "solutions",
            "management",
        }
    
        return {
            token
            for token in ResearchService._normalise_entity_text(
                value
            ).split()
            if len(token) >= 3 and token not in stop
        }
    
    
    def _entity_match(
        self,
        candidate: ProductCandidate,
        *,
        url: str,
        title: str = "",
        text: str = "",
        strict: bool = False,
    ) -> bool:
        """
        Verify that a search result actually refers to the product/vendor.
    
        This prevents:
        ExpressLane software != ExpressLane road
        ExpressLane software != ExpressLane insurance
        Smart Queue by Facit != generic 'smart queue' articles
        """
    
        vendor_domain = registrable(candidate.vendor_url)
        source_domain = registrable(url)
    
        if vendor_domain and source_domain == vendor_domain:
            return True
    
        haystack = self._normalise_entity_text(
            f"{title} {text}"
        )
    
        product = self._normalise_entity_text(
            candidate.product
        )
        vendor = self._normalise_entity_text(
            candidate.vendor
        )
    
        product_tokens = self._meaningful_tokens(
            candidate.product
        )
        vendor_tokens = self._meaningful_tokens(
            candidate.vendor
        )
    
        exact_product = bool(
            product and product in haystack
        )
    
        vendor_match = bool(
            vendor and vendor in haystack
        )
    
        if not vendor_match and vendor_tokens:
            vendor_match = any(
                token in haystack.split()
                for token in vendor_tokens
            )
    
        # Strongest independent-source match.
        if exact_product and vendor_match:
            return True
    
        # Strict customer-impact/evidence validation:
        # product name alone is not sufficient.
        if strict:
            return False
    
        # Review websites can sometimes omit the vendor name
        # from the title/snippet. Let Gemini examine these,
        # but they will NOT count unless it later classifies them.
        if any(
            domain in source_domain
            for domain in REVIEW_DOMAINS
        ):
            if exact_product:
                return True
    
        # Distinctive multi-token product names are safer.
        if len(product_tokens) >= 3:
            matched = sum(
                token in haystack.split()
                for token in product_tokens
            )
    
            if matched >= 2:
                return True
    
        return False
    
    
    def _classify_review_record(
        self,
        record: dict,
        target_product: str,
        vendor_domain: str,
    ) -> dict:
        """
        Deterministically classify review evidence.

        Supports:
        A. Individual user opinions (positive / neutral / negative)
        B. Verified aggregate ratings (normalised 0-100, labeled positive/neutral/negative, 1 record)
        C. Review count only ("16 verified reviews" -> labeled 'insufficient')
        D. Product description -> labeled 'insufficient'
        E. Vendor claim/testimonial -> excluded (independent=False, insufficient)
        F. Glassdoor employee reviews -> excluded (insufficient)
        G. Wrong-product collisions -> excluded (insufficient)
        """
        source_url = record.get("source_url", "")
        domain = registrable(source_url).lower()
        title = str(record.get("source_title", "")).strip()
        snippet = str(record.get("snippet", "")).strip()
        content = str(record.get("content_excerpt", "")).strip()
        corpus = f"{title} {snippet} {content}".strip()
        corpus_lower = corpus.lower()
        corpus_normalized = self._normalise_entity_text(corpus)

        # 1. Vendor independence
        if vendor_domain and domain == vendor_domain.lower():
            record["independent"] = False
            record["sentiment"] = "insufficient"
            record["classification_reason"] = "vendor_owned"
            return record

        # 2. Glassdoor employee reviews
        if domain in {"glassdoor.com", "glassdoor.co.uk"}:
            if any(w in corpus_lower for w in ["employer", "interview", "salary", "management", "benefits", "work culture", "coworkers", "ceo approval", "working at", "former employee", "current employee"]):
                record["sentiment"] = "insufficient"
                record["classification_reason"] = "employee_review"
                return record

        # 3. Wrong-product comparison check
        target_p_norm = self._normalise_entity_text(target_product)
        target_tokens = self._meaningful_tokens(target_product)
        url_lower = source_url.lower()
        normalized_url = self._normalise_entity_text(source_url)
        review_platform = any(d in domain for d in REVIEW_DOMAINS)
        url_identifies_target = bool(
            review_platform
            and target_p_norm
            and target_p_norm in normalized_url
        )
        g2_match = re.search(r"/(?:products|software)/([^/?#]+)/", url_lower)
        if g2_match:
            slug = g2_match.group(1).replace("-", " ")
            slug_norm = self._normalise_entity_text(slug)
            if target_p_norm and slug_norm and target_p_norm not in slug_norm and slug_norm not in target_p_norm:
                if not any(t in slug_norm for t in target_tokens):
                    record["sentiment"] = "insufficient"
                    record["classification_reason"] = "wrong_product_comparison"
                    return record
            url_identifies_target = bool(
                target_p_norm
                and (target_p_norm in slug_norm or slug_norm in target_p_norm)
            )

        # Product identity must be present in extracted text, except for a
        # review-platform URL whose canonical product path itself identifies the
        # target.  This keeps platform pages with sparse/JS-derived text from
        # being dropped while never treating an arbitrary mention as a review.
        if not (
            target_p_norm in corpus_normalized
            or any(t in corpus_normalized.split() for t in target_tokens)
            or url_identifies_target
        ):
            record["sentiment"] = "insufficient"
            record["classification_reason"] = "target_product_not_mentioned"
            return record

        # 4. Review count only check
        count_only_match = re.search(r"^\s*\d+[\d,]*\s+(?:verified\s+)?reviews?\.?\s*$", title.strip(), re.I)
        if count_only_match and len(snippet) < 40 and len(content) < 40:
            record["sentiment"] = "insufficient"
            record["classification_reason"] = "review_count_only"
            return record

        # 5. Verified aggregate rating detection
        rating_match_5 = re.search(r"\b([0-5](?:\.\d+)?)\s*(?:/|\s+out\s+of\s+)\s*5(?:\.0)?(?:\s+stars?)?\b", corpus_lower)
        rating_match_10 = re.search(r"\b([0-9](?:\.\d+)?|10(?:\.0)?)\s*(?:/|\s+out\s+of\s+)\s*10(?:\.0)?\b", corpus_lower)
        rating_match_100 = re.search(r"\b([0-9]{1,2}(?:\.\d+)?|100(?:\.0)?)\s*(?:/|\s+out\s+of\s+)\s*100(?:\.0)?\b", corpus_lower)
        review_count_match = re.search(r"\b(\d+[\d,]*)\s*(?:verified\s+)?(?:reviews?|ratings?|votes?)\b", corpus_lower)
        review_count = int(review_count_match.group(1).replace(",", "")) if review_count_match else None

        if rating_match_5:
            try:
                val = float(rating_match_5.group(1))
                norm_rating = (val / 5.0) * 100.0
                sentiment = "positive" if norm_rating >= 70.0 else ("neutral" if norm_rating >= 45.0 else "negative")
                record["sentiment"] = sentiment
                record["confidence"] = 0.85
                record["normalized_rating"] = round(norm_rating, 1)
                record["rating"] = val
                record["rating_scale"] = 5.0
                record["review_count"] = review_count
                record["is_aggregate"] = True
                record["classification_method"] = "deterministic_aggregate_rating"
                record["summary"] = f"Verified aggregate rating: {val}/5 based on {review_count or 'multiple'} reviews."
                return record
            except ValueError:
                pass

        if rating_match_10:
            try:
                val = float(rating_match_10.group(1))
                norm_rating = (val / 10.0) * 100.0
                sentiment = "positive" if norm_rating >= 70.0 else ("neutral" if norm_rating >= 45.0 else "negative")
                record["sentiment"] = sentiment
                record["confidence"] = 0.85
                record["normalized_rating"] = round(norm_rating, 1)
                record["rating"] = val
                record["rating_scale"] = 10.0
                record["review_count"] = review_count
                record["is_aggregate"] = True
                record["classification_method"] = "deterministic_aggregate_rating"
                record["summary"] = f"Verified aggregate rating: {val}/10 based on {review_count or 'multiple'} reviews."
                return record
            except ValueError:
                pass

        if rating_match_100:
            try:
                val = float(rating_match_100.group(1))
                sentiment = "positive" if val >= 80.0 else ("neutral" if val > 60.0 else "negative")
                record.update({"sentiment": sentiment, "confidence": 0.85, "normalized_rating": round(val, 1), "rating": val, "rating_scale": 100.0, "review_count": review_count, "is_aggregate": True, "classification_method": "deterministic_aggregate_rating", "summary": f"Verified aggregate rating: {val}/100 based on {review_count or 'multiple'} reviews."})
                return record
            except ValueError:
                pass

        # 6. Explicit user opinion language detection
        positive_phrases = (
            "easy to use", "easy to configure", "easy setup", "great tool",
            "saves us", "saves time", "time saving", "highly recommend",
            "excellent", "loved", "love this", "intuitive", "helpful support",
            "great support", "game changer", "fantastic", "very good",
            "best software", "satisfied", "seamless", "efficient", "powerful",
            "streamlined", "works great", "perfect solution", "reliable",
            "huge improvement", "great customer service", "super easy",
        )
        negative_phrases = (
            "poor support", "bad support", "difficult to configure", "hard to use",
            "bugs", "buggy", "crashed", "terrible", "waste of money", "waste of time",
            "lacks features", "missing features", "slow", "frustrating",
            "do not recommend", "not recommend", "disappointed", "unreliable",
            "hidden fees", "steep learning curve", "clunky", "expensive for what",
            "poor customer service", "worst", "awful", "regret buying",
        )
        neutral_phrases = (
            "adequate", "works adequately", "average", "mixed feelings",
            "mixed experience", "decent but", "good but lacks", "okay",
            "acceptable", "has pros and cons", "fair",
        )

        pos_count = sum(phrase in corpus_lower for phrase in positive_phrases)
        neg_count = sum(phrase in corpus_lower for phrase in negative_phrases)
        neu_count = sum(phrase in corpus_lower for phrase in neutral_phrases)

        if pos_count > 0 and neg_count == 0:
            record["sentiment"] = "positive"
            record["confidence"] = min(0.90, 0.65 + pos_count * 0.08)
            record["classification_method"] = "deterministic_opinion_language"
            record["summary"] = record.get("summary") or snippet[:200]
            return record
        elif neg_count > 0 and pos_count == 0:
            record["sentiment"] = "negative"
            record["confidence"] = min(0.90, 0.65 + neg_count * 0.08)
            record["classification_method"] = "deterministic_opinion_language"
            record["summary"] = record.get("summary") or snippet[:200]
            return record
        elif pos_count > 0 and neg_count > 0:
            record["sentiment"] = "neutral"
            record["confidence"] = 0.60
            record["classification_method"] = "deterministic_opinion_language"
            record["summary"] = record.get("summary") or snippet[:200]
            return record
        elif neu_count > 0:
            record["sentiment"] = "neutral"
            record["confidence"] = 0.60
            record["classification_method"] = "deterministic_opinion_language"
            record["summary"] = record.get("summary") or snippet[:200]
            return record

        record["sentiment"] = "insufficient"
        record["confidence"] = 0.0
        record["classification_reason"] = "no_opinion_language"
        record["classification_method"] = "unavailable"
        return record

    def _valid_review_record(
        self,
        row: dict,
        vendor_domain: str,
    ) -> bool:
        """
        A review counts toward sentiment only when classified with usable confidence
        from an independent non-vendor source.
        """
        if row.get("sentiment") not in {
            "positive",
            "neutral",
            "negative",
        }:
            return False

        try:
            confidence = float(row.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0

        if confidence < 0.45:
            return False

        source_domain = registrable(row.get("source_url", "")).lower()

        # Vendor testimonials are not independent sentiment
        if vendor_domain and source_domain == vendor_domain.lower():
            return False

        # Glassdoor employee reviews are not product-user sentiment
        if source_domain in {"glassdoor.com", "glassdoor.co.uk"}:
            corpus = str(row.get("content_excerpt") or row.get("snippet") or "").lower()
            if any(w in corpus for w in ["employer", "interview", "salary", "management", "benefits", "work culture", "coworkers", "ceo approval", "working at", "former employee", "current employee"]):
                return False

        return True
    
    
    @staticmethod
    def _calculate_sentiment_score(
        reviews: list[dict],
    ) -> float | None:
        """
        Deterministic sentiment score.
    
        Positive = +1, neutral = 0, negative = -1. Scores use classified
        retained evidence rather than confidence weighting.
        """
    
        mapping = {"positive": 1, "neutral": 0, "negative": -1}
        total = 0
        classified = 0
    
        for row in reviews:
            label = row.get("sentiment")
    
            if label not in mapping:
                continue
    
            total += mapping[label]
            classified += 1
        if not classified:
            return None
        return round(50.0 + (total / classified * 50.0), 1)
    
    @staticmethod
    def _merge_evidence(
        *groups,
        limit: int = 35,
    ):
        seen = set()
        out = []

        for group in groups:
            for item in group or []:
                if isinstance(
                    item,
                    dict,
                ):
                    try:
                        item = EvidenceItem.model_validate(
                            item
                        )
                    except Exception:
                        continue

                if (
                    not isinstance(
                        item,
                        EvidenceItem,
                    )
                    or not item.source_url
                ):
                    continue

                key = (
                    item.source_url.rstrip("/"),
                    item.claim.lower().strip()[:140],
                )

                if key in seen:
                    continue

                seen.add(
                    key
                )

                out.append(
                    item
                )

                if len(out) >= limit:
                    return out

        return out

    async def _collect_deep_bundle(
        self,
        req: ResearchRequest,
        candidate: ProductCandidate,
    ):
        """Collect and preserve deep-research evidence without calling Gemini.

        Serper discovers sources, Jina extracts readable text, and Python performs
        entity filtering before any LLM interpretation. The raw/retained material is
        kept in the returned bundle so the final output remains auditable.
        """
        domain = registrable(candidate.vendor_url)
        logger.info("[3/7] Evidence collection: %s", candidate.product)

        product_vendor = (
            f'"{candidate.product}"'
            if self._normalise_entity_text(candidate.product) == self._normalise_entity_text(candidate.vendor)
            else f'"{candidate.product}" "{candidate.vendor}"'
        )
        product_exact = f'"{candidate.product}"'
        vendor_exact = f'"{candidate.vendor}"'
        evidence_queries = [
            f"{product_vendor} {req.sector} {req.business_goal}",
            f"site:{domain} {product_vendor} customer case study outcomes",
            f"{product_exact} case study", f"{product_exact} customer success",
            f"{product_exact} implementation", f"{product_exact} customer results",
            f"{product_exact} fuel savings", f"{product_exact} cost reduction",
            f"{product_exact} ROI", f"{product_exact} productivity improvement",
            f"{product_exact} implementation results", f"{product_exact} customer outcomes",
            f"{product_exact} pricing", f"{product_exact} cost",
            f"{product_exact} licence fee", f"{product_exact} subscription",
            f"{vendor_exact} annual report", f"{vendor_exact} revenue",
            f"{vendor_exact} financial statements", f"{vendor_exact} Companies House",
        ]
        outcome_terms = self._outcome_search_terms(req)
        customer_queries = [
            f"{product_exact} customer", f"{product_exact} used by",
            f"{product_exact} deployed by", f"{product_exact} implemented by",
            f"{product_exact} company case study", f"{product_exact} logistics customer",
            f"{product_exact} fleet customer", f"{product_exact} customer story",
        ] + [f"{product_vendor} {term}" for term in outcome_terms]
        review_queries = [
            f"{product_exact} reviews", f"{product_exact} customer reviews",
            f"{product_exact} user experience", f"{product_exact} customer feedback",
            f"site:g2.com {product_exact}", f"site:capterra.com {product_exact}",
            f"site:getapp.com {product_exact}", f"site:trustradius.com {product_exact}",
            f"site:gartner.com/reviews {product_exact}", f"site:peerspot.com {product_exact}",
            f"site:softwareadvice.com {product_exact}",
        ]

        evidence_hits, customer_hits, review_hits = await asyncio.gather(
            self._search_many(evidence_queries, num=10),
            self._customer_search_many(customer_queries, num=10),
            self._search_many(review_queries, num=10),
        )
        # One recovery round is deliberately bounded and only runs when an
        # initial source family returned no candidates.  It uses the canonical
        # product/vendor pair rather than broadening to generic market terms.
        recovery_attempted = False
        has_pricing_candidate = any(
            term in f"{h.title} {h.snippet} {h.url}".lower()
            for h in evidence_hits
            for term in ("pricing", "price", "cost", "subscription", "licence", "license")
        )
        if not review_hits or not customer_hits or not has_pricing_candidate:
            recovery_attempted = True
            recovery_evidence, recovery_customers, recovery_reviews = await asyncio.gather(
                self._search_many([
                    f"{product_exact} {vendor_exact} pricing cost",
                    f"{product_exact} {vendor_exact} customer outcomes",
                ], num=10),
                self._customer_search_many([
                    f"{product_exact} {vendor_exact} customer implementation",
                    f"{product_exact} {vendor_exact} case study",
                ], num=10),
                self._search_many([
                    f"{product_exact} {vendor_exact} reviews",
                    f"site:g2.com {product_exact} {vendor_exact}",
                ], num=10),
            )
            evidence_hits = self._merge_search_results(evidence_hits, recovery_evidence)
            customer_hits = self._merge_search_results(customer_hits, recovery_customers)
            review_hits = self._merge_search_results(review_hits, recovery_reviews)
        raw_evidence_count = len(evidence_hits) + len(customer_hits) + len(review_hits)
        customer_search_count = len(customer_hits)
        queries_attempted = len(evidence_queries) + len(customer_queries) + len(review_queries) + (6 if recovery_attempted else 0)
        all_discovery_hits = self._merge_search_results(evidence_hits, customer_hits, review_hits)
        source_type_counts: dict[str, int] = {}
        for hit in all_discovery_hits:
            source_type = self._discovery_source_type(hit, domain)
            source_type_counts[source_type] = source_type_counts.get(source_type, 0) + 1
        customer_signals = (
            "case stud", "customer stor", "customer success", "result", "roi", "saved",
            "reduced", "increased", "improved", "efficiency", "productivity",
            "waiting time", "processing time", "labour", "cost saving", "revenue",
            "conversion", "payback",
        )
        # Snippets are discovery-only.  Promising customer pages are read before
        # strict page-level product/customer validation, rather than discarded
        # because a terse search snippet omitted the vendor name.
        promising_customer_hits = [
            h for h in customer_hits
            if any(signal in f"{h.title} {h.snippet} {h.url}".lower() for signal in customer_signals)
        ]
        evidence_hits = self._merge_search_results(evidence_hits, customer_hits)

        # Search snippets are discovery-only.  Do not discard promising case
        # studies, pricing pages, or independent sources merely because their
        # snippet omits the product name; verify them after Jina reads the page.
        evidence_signals = (
            "case stud", "customer", "implementation", "deployed", "adopted",
            "result", "roi", "saving", "reduced", "increased", "pricing",
            "price", "cost", "review", "testimonial",
        )
        pre_read_hits = [
            h for h in evidence_hits
            if self._entity_match(candidate, url=h.url, title=h.title, text=h.snippet, strict=False)
            or registrable(h.url) == domain
            or any(signal in f"{h.title} {h.snippet} {h.url}".lower() for signal in evidence_signals)
        ]
        known_urls = {h.url.rstrip("/") for h in pre_read_hits}
        pre_read_hits.extend(h for h in promising_customer_hits if h.url.rstrip("/") not in known_urls)
        raw_review_hits = list(review_hits)
        review_hits = [
            h for h in raw_review_hits
            if self._is_relevant_review_hit(candidate.product, h, candidate.vendor)
        ]
        review_relevant_count = len(review_hits)

        # Search snippets are only discovery metadata.  A known review platform
        # can omit the product/vendor from a result card even though its page has
        # the identity and opinion text.  Keep such a hit only when the query
        # itself was product/vendor-targeted; the extracted page must still pass
        # the product check in _classify_review_record before it can count.
        product_query = self._normalise_entity_text(
            f"{candidate.product} {candidate.vendor}"
        )
        review_hits = [
            h for h in review_hits
            if self._entity_match(
                candidate, url=h.url, title=h.title, text=h.snippet, strict=False
            )
            or (
                any(d in registrable(h.url).lower() for d in REVIEW_DOMAINS)
                and any(
                    token in self._normalise_entity_text(getattr(h, "query", ""))
                    for token in self._meaningful_tokens(product_query)
                )
            )
        ][:25]

        # Outcome/pricing-labelled pages go first: snippets discover sources, but
        # claims are accepted only after the underlying page has been read.
        pre_read_hits.sort(key=lambda h: 0 if any(term in f"{h.title} {h.snippet} {h.url}".lower() for term in ("case stud", "customer stor", "success", "result", "roi", "saving", "pricing", "price", "cost")) else 1)
        general_pages = await self._read_pages([h.url for h in pre_read_hits], 18)
        page_by_url = {p.get("url"): p for p in general_pages}
        evidence_hits = [
            h for h in pre_read_hits
            if registrable(h.url) == domain
            or self._entity_match(
                candidate, url=h.url, title=h.title,
                text=(page_by_url.get(h.url, {}).get("content") or h.snippet), strict=False,
            )
        ]
        review_pages = await self._read_pages([h.url for h in review_hits], 8)
        page_by_url = {p.get("url"): p for p in review_pages}

        logger.info(
            "[REVIEW PIPELINE] product=%s search_results=%s review_relevant=%s selected_urls=%s pages_read=%s pages_with_text=%s",
            candidate.product,
            len(raw_review_hits),
            review_relevant_count,
            len(review_hits),
            len(review_pages),
            sum(bool(p.get("content")) for p in review_pages),
        )

        retained_source_evidence = self._evidence_from_hits(
            evidence_hits, general_pages, domain, target=30
        )
        logger.info(
            "[EVIDENCE] product=%s raw=%s unique=%s relevant=%s pages_selected=%s pages_read=%s verified=%s",
            candidate.product,
            raw_evidence_count,
            len(self._merge_search_results(evidence_hits, review_hits)),
            len(evidence_hits),
            min(18, len(pre_read_hits)),
            len(general_pages),
            len(retained_source_evidence),
        )

        review_records = []
        for h in review_hits:
            page = page_by_url.get(h.url, {})
            review_records.append({
                "product": candidate.product,
                "vendor": candidate.vendor,
                "source_url": h.url,
                "source_title": h.title or page.get("title", ""),
                "source_domain": registrable(h.url),
                "platform": self._platform(h.url),
                "source_type": self._discovery_source_type(h, domain),
                "snippet": self._plain(h.snippet, 500),
                "content_excerpt": self._plain(
                    page.get("content") or h.snippet, 1200
                ),
                "sentiment": "unclassified",
                "reviewer_name": "",
                "reviewer_organisation": "",
                "review_text": "",
                "evidence_quote": "",
                "is_opinion_bearing": False,
                "is_customer_review": False,
                "summary": "",
                "confidence": 0.0,
                "themes": [],
                "independent": registrable(h.url) != domain,
                "entity_match": True,
                "classification_method": "gemini_compact_verified_excerpt",
            })

        evidence_corpus = "\n\n".join(
            f'URL: {p["url"]}\nTITLE: {p.get("title", "")}\n'
            f'CONTENT: {self._plain(p.get("content", ""), 4500)}'
            for p in general_pages
        )
        review_corpus = "\n\n".join(
            f'URL: {r["source_url"]}\nPLATFORM: {r["platform"]}\n'
            f'TITLE: {r["source_title"]}\n'
            f'TEXT: {r["content_excerpt"] or r["snippet"]}'
            for r in review_records
        )

        return {
            "candidate": candidate,
            "domain": domain,
            "evidence_hits": evidence_hits,
            "review_hits": review_hits,
            "general_pages": general_pages,
            "review_pages": review_pages,
            "retained_source_evidence": retained_source_evidence,
            "review_records": review_records,
            "deterministic_impacts": self._deterministic_customer_impacts(candidate, general_pages, domain),
            "customer_impact_diagnostics": {
                "queries_attempted": queries_attempted,
                "recovery_attempted": recovery_attempted,
                "search_results": customer_search_count,
                "promising_urls": len(promising_customer_hits),
                "selected_urls": len({h.url.rstrip("/") for h in pre_read_hits if h.url.rstrip("/") in {x.url.rstrip("/") for x in promising_customer_hits}}),
                "pages_read": len(general_pages),
                "pages_with_text": sum(bool(p.get("content")) for p in general_pages),
                "pages_failed": max(0, min(12, len(evidence_hits)) - len(general_pages)),
                "deterministic_impacts": len(self._deterministic_customer_impacts(candidate, general_pages, domain)),
            },
            "review_diagnostics": {
                "search_results": len(raw_review_hits),
                "review_relevant": review_relevant_count,
                "selected_urls": len(review_hits),
                "pages_read": len(review_pages),
                "pages_with_text": sum(bool(p.get("content")) for p in review_pages),
            },
            "evidence_diagnostics": {
                "queries_attempted": queries_attempted,
                "recovery_attempted": recovery_attempted,
                "source_types_found": source_type_counts,
                "raw_results": raw_evidence_count,
                "unique_results": len(self._merge_search_results(evidence_hits, review_hits)),
                "relevant_results": len(evidence_hits),
                "pages_read": len(general_pages),
                "verified_evidence": len(retained_source_evidence),
            },
            # Keep enough text for strong extraction while bounding each batch prompt.
            "evidence_corpus": evidence_corpus[:18000],
            "review_corpus": review_corpus[:9000],
        }

    def _build_compact_evidence_pack(self, bundle: dict, compact: bool = False) -> dict:
        """Return small, deduplicated excerpts for one product-level LLM call."""
        excerpt_limit = 500 if compact else 800
        limits = (5, 8, 6, 4) if compact else (8, 12, 10, 6)
        domain = bundle.get("domain", "")
        # Include both general and review pages so Jina-extracted review text is passed
        pages = {
            p.get("url"): p
            for p in (bundle.get("general_pages", []) + bundle.get("review_pages", []))
            if isinstance(p, dict) and p.get("url")
        }

        def records(hits, limit, require_independent=False):
            out, seen = [], set()
            for hit in hits:
                url = hit.url.rstrip("/")
                if not url or url in seen:
                    continue
                if require_independent and registrable(url) == domain:
                    continue
                page = pages.get(hit.url, {})
                text = self._plain(page.get("content") or hit.snippet, excerpt_limit)
                if not text:
                    continue
                seen.add(url)
                out.append({"url": hit.url, "title": hit.title, "domain": registrable(hit.url), "text": text})
                if len(out) >= limit:
                    break
            return out

        evidence = bundle.get("evidence_hits", [])
        reviews = bundle.get("review_hits", [])
        customer_hits = [h for h in evidence if any(x in f"{h.title} {h.snippet} {h.url}".lower() for x in ("customer", "case stud", "client", "success stor"))]
        pricing_hits = [h for h in evidence if any(x in f"{h.title} {h.snippet} {h.url}".lower() for x in ("pricing", "price", "cost", "plan"))]
        return {
            "general_evidence": records(evidence, limits[0]),
            "review_sources": records(reviews, limits[1], require_independent=True),
            "customer_sources": records(customer_hits, limits[2]),
            "pricing_sources": records(pricing_hits, limits[3]),
        }

    async def _apply_deep_analysis(
        self,
        req: ResearchRequest,
        candidate: ProductCandidate,
        deep: DeepProductResearch,
        bundle: dict,
    ):
        """Apply one structured Gemini interpretation using deterministic checks."""
        domain = bundle["domain"]
        evidence_hits = bundle["evidence_hits"]
        review_hits = bundle["review_hits"]
        general_pages = bundle["general_pages"]
        review_pages = bundle["review_pages"]
        retained_source_evidence = bundle["retained_source_evidence"]
        review_records = bundle["review_records"]

        assessments = {
            x.source_url.rstrip("/"): x
            for x in deep.review_assessments
        }

        # Step 1: Apply Gemini assessments where confident
        for row in review_records:
            a = assessments.get(row["source_url"].rstrip("/"))
            if a and a.sentiment in {"positive", "neutral", "negative"} and a.confidence >= 0.45:
                row["sentiment"] = a.sentiment
                row["summary"] = a.summary or row.get("snippet", "")[:200]
                row["confidence"] = a.confidence
                row["themes"] = a.themes
                row["classification_method"] = "gemini_structured"

        # Step 2: For any unclassified or insufficient records, apply deterministic classification
        for row in review_records:
            if row.get("sentiment") not in {"positive", "neutral", "negative"}:
                self._classify_review_record(row, candidate.product, domain)
            row["is_opinion_bearing"] = row.get("sentiment") in {"positive", "neutral", "negative"}
            row["is_customer_review"] = bool(
                row["is_opinion_bearing"]
                and row.get("source_type") == "independent_review"
            )
            row["review_text"] = row.get("content_excerpt") or row.get("snippet", "")
            row["evidence_quote"] = self._plain(row["review_text"], 420)

        # Step 3: Deduplicate review records by canonical URL / platform
        deduped_records = []
        seen_keys = set()
        duplicates_removed_count = 0
        for row in review_records:
            url_key = str(row.get("source_url", "")).rstrip("/").lower()
            key = (row.get("platform", "Web"), url_key)
            if key in seen_keys:
                duplicates_removed_count += 1
                continue
            seen_keys.add(key)
            deduped_records.append(row)
        review_records = deduped_records

        if (
            deep.currency
            and deep.currency.upper()
            != "GBP"
        ):
            original = (
                deep.currency.upper()
            )

            annual = await self.fx.convert(
                deep.annual_software_cost,
                original,
                "GBP",
            )

            implementation = (
                await self.fx.convert(
                    deep.implementation_cost,
                    original,
                    "GBP",
                )
            )

            if (
                deep.annual_software_cost
                is None
                or annual is not None
            ):
                deep.annual_software_cost = (
                    annual
                )

            if (
                deep.implementation_cost
                is None
                or implementation
                is not None
            ):
                deep.implementation_cost = (
                    implementation
                )

            if (
                (
                    deep.annual_software_cost
                    is None
                    or annual is not None
                )
                and (
                    deep.implementation_cost
                    is None
                    or implementation
                    is not None
                )
            ):
                deep.currency = "GBP"

                deep.pricing_basis = (
                    deep.pricing_basis
                    + " | Converted to GBP in Python "
                    "using Frankfurter FX."
                ).strip(
                    " |"
                )

        classified_reviews = [
            r
            for r in review_records
            if r.get("sentiment")
            in {"positive", "neutral", "negative"}
        ]

        usable_reviews = [
            r
            for r in classified_reviews
            if self._valid_review_record(
                r,
                domain,
            )
        ]

        independent_reviews = [
            r
            for r in usable_reviews
            if registrable(r["source_url"]).lower() != domain.lower()
        ]

        independent_review_domains = {
            registrable(r["source_url"]).lower()
            for r in independent_reviews
            if registrable(r["source_url"])
        }

        classified_platforms = {
            r["platform"]
            for r in usable_reviews
            if r["platform"] != "Web"
        }

        sentiment_sufficient = (
            len(independent_reviews) >= 3
            and len(independent_review_domains) >= 2
        )

        entity_matched_count = sum(1 for r in review_records if r.get("classification_reason") != "target_product_not_mentioned")
        independent_count = sum(1 for r in review_records if registrable(r.get("source_url", "")).lower() != domain.lower())
        opinion_bearing_count = len(classified_reviews)
        insufficient_count = len(review_records) - len(classified_reviews)
        deterministic_count = sum(
            str(r.get("classification_method", "")).startswith("deterministic")
            for r in usable_reviews
        )
        gemini_count = sum(
            r.get("classification_method") == "gemini_structured"
            for r in usable_reviews
        )
        sentiment_counts = {
            label: sum(r.get("sentiment") == label for r in usable_reviews)
            for label in ("positive", "neutral", "negative")
        }

        logger.info(
            "[SENTIMENT PIPELINE] product=%s extracted_records=%s entity_matched=%s independent=%s opinion_bearing=%s deterministically_classified=%s gemini_classified=%s total_classified=%s positive=%s neutral=%s negative=%s insufficient=%s duplicates_removed=%s score=%s evidence_sufficient=%s",
            candidate.product, len(review_records) + duplicates_removed_count,
            entity_matched_count, independent_count, opinion_bearing_count,
            deterministic_count, gemini_count, len(usable_reviews),
            sentiment_counts["positive"], sentiment_counts["neutral"],
            sentiment_counts["negative"], insufficient_count,
            duplicates_removed_count, candidate.sentiment_score, sentiment_sufficient,
        )

        candidate.reviews = (
            review_records
        )

        candidate.sentiment_score = self._calculate_sentiment_score(independent_reviews)

        candidate.sentiment_summary = {
            "score": candidate.sentiment_score,
            "evidence_sufficient": (
                sentiment_sufficient
            ),
            "sentiment_analysis_status": "complete" if usable_reviews else "unknown_no_classified_reviews",
            "review_evidence_found": len(review_records),
            "opinion_bearing_reviews_found": len(classified_reviews),
            "analysis_unavailable": False,
            "positive_themes": (
                deep.positive_themes
                if sentiment_sufficient
                else []
            ),
            "negative_themes": (
                deep.negative_themes
                if sentiment_sufficient
                else []
            ),
            "source_count": len(
                review_records
            ),
            "classified_review_count": len(
                usable_reviews
            ),
            "independent_review_count": len(
                independent_reviews
            ),
            "independent_review_domains": len(
                independent_review_domains
            ),
            "classified_platform_count": len(
                classified_platforms
            ),
            "positive_count": sum(r.get("sentiment") == "positive" for r in usable_reviews),
            "neutral_count": sum(r.get("sentiment") == "neutral" for r in usable_reviews),
            "negative_count": sum(r.get("sentiment") == "negative" for r in usable_reviews),
            "target_source_count": 25,
        }

        source_context = {}
        for h in evidence_hits:
            source_context[h.url.rstrip("/")] = (
                h.title,
                h.snippet,
            )
        for p in general_pages:
            source_context[p.get("url", "").rstrip("/")] = (
                p.get("title", ""),
                self._plain(p.get("content", ""), 3000),
            )

        def source_matches_entity(source_url: str) -> bool:
            if not source_url:
                return False
            src_dom = registrable(source_url).lower()
            if domain and src_dom == domain.lower():
                return True
            key = source_url.rstrip("/")
            key = (source_url or "").rstrip("/")
            title, body = source_context.get(key, ("", ""))
            return self._entity_match(
                candidate,
                url=source_url,
                title=title,
                text=body,
                strict=False,
            )

        customer_seen: set[tuple[str, str]] = set()
        candidate.customers = []
        customer_source_records = len(deep.customers)
        customer_entity_matched = 0
        customer_explicit_relationships = 0
        vague_customer_terms = (
            "leading retailer", "leading retailers", "major retailer", "major retailers",
            "top retailer", "top retailers", "various clients", "several clients",
            "global brand", "enterprise customer", "anonymous", "undisclosed", "leading company",
        )
        for customer in deep.customers:
            if not customer.source_url or not source_matches_entity(customer.source_url):
                continue
            customer_entity_matched += 1
            record = customer.model_dump()
            cust_name = str(record.get("customer") or "").strip()
            if not cust_name or len(cust_name) < 2 or any(v in cust_name.lower() for v in vague_customer_terms):
                continue
            source_title, source_body = source_context.get(
                customer.source_url.rstrip("/"), ("", "")
            )
            relation_text = f"{source_title} {source_body}".lower()
            customer_tokens = self._meaningful_tokens(cust_name)
            if (
                not customer_tokens
                or not all(token in relation_text for token in customer_tokens)
                or not re.search(r"\b(?:uses?|used|implemented|deployed|adopted|rolled\s+out)\b", relation_text)
            ):
                continue
            customer_explicit_relationships += 1
            record["product"] = candidate.product
            record["vendor_name"] = candidate.vendor
            record["customer_name"] = cust_name
            record["customer_country"] = ""
            record["is_explicit_product_use"] = True
            record["source_domain"] = registrable(customer.source_url)
            src_dom = registrable(customer.source_url).lower()
            record["source_type"] = "vendor_case_study" if (domain and src_dom == domain.lower()) else "independent_case_study"
            record["is_independent"] = record["source_type"] != "vendor_case_study"
            record["evidence_quote"] = self._plain(source_body, 420)
            key = (cust_name.casefold(), customer.source_url.rstrip("/"))
            if key in customer_seen:
                continue
            customer_seen.add(key)
            candidate.customers.append(record)

        candidate.customer_impact = []
        rejected_adoption_scale = 0
        numeric_candidates = 0
        outcome_terms = (
            "reduced", "reduction", "increased", "increase", "saved", "saving",
            "generated", "roi", "payback", "improved", "improvement", "faster", "decreased",
            "decrease", "cut", "drop", "dropped", "down", "boost", "boosted",
            "lower", "less", "quicker", "productivity", "efficiency", "%", "percent",
            "wait time", "waiting time", "queue time", "throughput", "labour", "hours",
        )
        # Deterministic claims supplement (never replace) structured extraction,
        # so explicit outcomes survive Gemini 429/503 failures.
        raw_impacts = [item.model_dump() for item in deep.impacts] + bundle.get("deterministic_impacts", [])
        impact_seen: set[tuple[str, str, str]] = set()
        for item in raw_impacts:
            if isinstance(item, dict):
                record = dict(item)
            else:
                continue
            page_extracted = record.get("extraction_method") == "deterministic_page_pattern"
            if not record.get("source_url") or (not page_extracted and not source_matches_entity(record["source_url"])):
                continue
            record["product"] = candidate.product
            scope = self._impact_scope(record)
            record["impact_scope"] = scope
            if scope == "adoption_scale":
                rejected_adoption_scale += 1
                logger.info("[IMPACT] REJECTED: %s | %s | adoption_scale", record.get("customer"), record.get("claim") or record.get("metric"))
                continue
            if not isinstance(record.get("impact_value"), (int, float)):
                continue
            numeric_candidates += 1
            context = " ".join(str(record.get(key) or "") for key in ("metric", "claim", "application")).lower()
            if not any(term in context for term in outcome_terms):
                continue
            impact_key = (record["source_url"].rstrip("/"), str(record.get("customer") or "").casefold(), str(record.get("claim") or "")[:140])
            if impact_key in impact_seen:
                continue
            impact_seen.add(impact_key)
            candidate.customer_impact.append(record)
            logger.info("[IMPACT] KEPT: %s | %s | %s", record.get("customer"), scope, record.get("impact_value"))

        await self._enrich_customer_financials(candidate)

        logger.info("[CUSTOMERS] Verified customers: %s", len(candidate.customers))
        logger.info("[CUSTOMERS] %s: %s named customers retained", candidate.product, len(candidate.customers))
        logger.info("[IMPACT] %s: %s explicit numeric claims", candidate.product, len([x for x in candidate.customer_impact if isinstance(x.get("impact_value"), (int, float))]))
        logger.info("[IMPACT] %s numeric candidates: %s", candidate.product, numeric_candidates)
        logger.info("[IMPACT] %s adoption-scale numbers rejected: %s", candidate.product, rejected_adoption_scale)
        logger.info("[IMPACT] %s verified business outcomes: %s", candidate.product, len(candidate.customer_impact))
        diagnostics = bundle.get("customer_impact_diagnostics", {})
        operational_impacts = sum(x.get("classification") == "operational" for x in candidate.customer_impact)
        financial_impacts = sum(x.get("classification") == "financial" for x in candidate.customer_impact)
        logger.info(
            "[CUSTOMER IMPACT] product=%s search_results=%s promising_urls=%s pages_read=%s pages_failed=%s customer_relationships_verified=%s numeric_candidates=%s adoption_numbers_rejected=%s operational_impacts=%s financial_impacts=%s verified_impacts=%s",
            candidate.product, diagnostics.get("search_results", 0), diagnostics.get("promising_urls", 0), diagnostics.get("pages_read", 0), diagnostics.get("pages_failed", 0), len(candidate.customers), numeric_candidates, rejected_adoption_scale, operational_impacts, financial_impacts, len(candidate.customer_impact),
        )

        independent_customers = sum(
            registrable(row.get("source_url", "")).lower() != domain.lower()
            for row in candidate.customers
        )
        logger.info(
            "[CUSTOMER PIPELINE] product=%s model_customer_records=%s entity_matched=%s explicit_relationships=%s named_customers=%s independent_customer_evidence=%s explicit_impacts=%s analysis_status=%s",
            candidate.product,
            customer_source_records,
            customer_entity_matched,
            customer_explicit_relationships,
            len(candidate.customers),
            independent_customers,
            len(candidate.customer_impact),
            "complete" if candidate.customers else "unknown_no_explicit_customer_evidence",
        )

        verified_numeric_impacts = [
            x
            for x in candidate.customer_impact
            if isinstance(x.get("impact_value"), (int, float))
        ]

        candidate.impact_score = (
            deep.impact_score
            if candidate.customer_impact
            else 50.0
        )

        candidate.annual_software_cost = (
            deep.annual_software_cost
        )

        candidate.currency = deep.currency
        candidate.pricing_basis = deep.pricing_basis

        # A structured response may omit an explicit price that is already in
        # retained pricing evidence. Recover it deterministically; no new search.
        if candidate.annual_software_cost is None:
            pricing = self._extract_retained_pricing(candidate, evidence_hits, general_pages)
            candidate.annual_software_cost = pricing["annual_cost"]
            candidate.currency = pricing["currency"]
            candidate.pricing_basis = pricing["basis"]
            candidate.pricing_confidence = pricing["confidence"]
            candidate.pricing_evidence = pricing["evidence"]
            if candidate.annual_software_cost is not None and candidate.currency != "GBP":
                converted = await self.fx.convert(candidate.annual_software_cost, candidate.currency, "GBP")
                if converted is not None:
                    candidate.annual_software_cost = converted
                    candidate.currency = "GBP"
                    candidate.pricing_basis = f"{candidate.pricing_basis} | Converted to GBP in Python using Frankfurter FX."
                else:
                    candidate.annual_software_cost = None

        candidate.implementation_cost = (
            deep.implementation_cost
        )

        if not candidate.pricing_evidence:
            candidate.pricing_confidence = deep.pricing_confidence
            candidate.pricing_evidence = [x.model_dump() for x in deep.pricing_evidence]

        pricing_pages_read = sum(
            1 for p in general_pages
            if any(term in f"{p.get('title', '')} {p.get('content', '')[:500]} {p.get('url', '')}".lower() for term in ("pricing", "price", "plan", "subscription", "cost"))
        )
        logger.info(
            "[PRODUCT FINANCIALS] product=%s pricing_search_results=%s pricing_pages_read=%s pricing_candidates=%s verified_prices=%s annual_cost=%s implementation_cost=%s pricing_basis=%s",
            candidate.product,
            sum(1 for h in evidence_hits if any(term in f"{h.title} {h.snippet} {h.url}".lower() for term in ("pricing", "price", "plan", "subscription", "cost"))),
            pricing_pages_read, len(candidate.pricing_evidence), int(candidate.annual_software_cost is not None), candidate.annual_software_cost, candidate.implementation_cost, candidate.pricing_basis,
        )

        candidate.risks = (
            deep.risks
        )

        merged = self._merge_evidence(
            deep.quality_evidence,
            deep.pricing_evidence,
            candidate.evidence,
            retained_source_evidence,
            limit=35,
        )

        known_urls = {
            h.url.rstrip("/")
            for h in evidence_hits + review_hits
            if h.url
        }
        known_urls.add(candidate.vendor_url.rstrip("/"))

        candidate.evidence = [
            item
            for item in merged
            if (
                item.source_url.rstrip("/") in known_urls
                or registrable(item.source_url) == domain
            )
            and self._entity_match(
                candidate,
                url=item.source_url,
                title=item.source_title,
                text=(
                    f"{item.claim} {item.supporting_text}"
                ),
                strict=False,
            )
        ][:35]

        retained_count = len(
            candidate.evidence
        )

        unique_domains = {
            registrable(
                x.source_url
            )
            for x in candidate.evidence
            if x.source_url
        }

        independent_sources = [
            x
            for x in candidate.evidence
            if registrable(
                x.source_url
            ) != domain
        ]

        vendor_sources = (
            retained_count
            - len(
                independent_sources
            )
        )

        weighted_points = sum(
            self._evidence_weight(
                x,
                domain,
            )
            for x in candidate.evidence
        )

        weighted_coverage_score = min(
            100.0,
            (
                weighted_points
                / 30.0
            )
            * 100.0,
        )

        diversity_score = min(
            100.0,
            (
                len(
                    unique_domains
                )
                / 10.0
            )
            * 100.0,
        )

        candidate.evidence_score = round(
            (
                candidate.evidence_score
                * 0.35
            )
            + (
                weighted_coverage_score
                * 0.45
            )
            + (
                diversity_score
                * 0.20
            ),
            2,
        )

        quantified_impacts = len(
            verified_numeric_impacts
        )

        candidate.evidence_coverage = {
            "target": 30,
            "search_results_found": len(
                evidence_hits
            ),
            "pages_read": len(
                general_pages
            ),
            "retained": retained_count,
            "weighted_evidence_score": round(
                weighted_coverage_score,
                1,
            ),
            "unique_domains": len(
                unique_domains
            ),
            "independent_sources": len(
                independent_sources
            ),
            "vendor_sources": (
                vendor_sources
            ),
            "review_target": 25,
            "review_sources_found": len(
                review_records
            ),
            "classified_review_count": len(
                usable_reviews
            ),
            "independent_review_count": len(
                independent_reviews
            ),
            "review_pages_read": len(
                review_pages
            ),
            "quantified_impact_claims": (
                quantified_impacts
            ),
            "pricing_sources": len(
                deep.pricing_evidence
            ),
            "named_customers": len(candidate.customers),
            "independent_customer_evidence": independent_customers,
            "customer_use_evidence_found": len(candidate.customers),
            "customer_use_analysis_status": "complete" if candidate.customers else "unknown_no_explicit_customer_evidence",
            "recommendation_status": "VALIDATED" if sentiment_sufficient and candidate.customers else "PROVISIONAL_INSUFFICIENT_EVIDENCE",
            "fmp_resolved_customers": len([x for x in candidate.customers if (x.get("financial_context") or {}).get("status") == "available"]),
        }

        discovery = bundle.get("evidence_diagnostics", {})
        review_diagnostics = bundle.get("review_diagnostics", {})
        evidence_status = (
            "FOUND" if usable_reviews and candidate.customers
            else "PARTIAL" if (usable_reviews or candidate.customers or candidate.customer_impact or candidate.pricing_evidence)
            else "NOT_FOUND_AFTER_SEARCH"
        )
        candidate.evidence_coverage.update({
            "queries_attempted": discovery.get("queries_attempted", 0),
            "total_search_results": discovery.get("raw_results", 0),
            "review_platform_results": sum(
                count for source_type, count in discovery.get("source_types_found", {}).items()
                if source_type == "independent_review"
            ),
            "review_candidates": review_diagnostics.get("review_relevant", 0),
            "selected_review_urls": review_diagnostics.get("selected_urls", 0),
            "review_pages_with_text": review_diagnostics.get("pages_with_text", 0),
            "opinion_bearing_reviews": opinion_bearing_count,
            "impact_records": len(candidate.customer_impact),
            "verified_financial_records": len(candidate.pricing_evidence),
            "source_types_found": discovery.get("source_types_found", {}),
            "evidence_status": evidence_status,
            "evidence_unavailable_message": (
                "No classified customer reviews were found after searching the configured product-review, customer-case-study and implementation-source families. No explicit named customer-use evidence was identified. No verified product pricing or financial metrics were available."
                if evidence_status == "NOT_FOUND_AFTER_SEARCH" else ""
            ),
        })
        logger.info(
            "[RESEARCH EVIDENCE]\nproduct=%s\nqueries_attempted=%s\nsearch_results=%s\nreview_candidates=%s\nselected_review_urls=%s\npages_with_text=%s\nclassified_reviews=%s\nnamed_customers=%s\nexplicit_customer_use=%s\nindependent_customer_use=%s\nimpact_records=%s\nverified_financial_records=%s\nstatus=%s",
            candidate.product, discovery.get("queries_attempted", 0), discovery.get("raw_results", 0),
            review_diagnostics.get("review_relevant", 0), review_diagnostics.get("selected_urls", 0),
            review_diagnostics.get("pages_with_text", 0), len(usable_reviews), len(candidate.customers),
            len(candidate.customers), independent_customers, len(candidate.customer_impact),
            len(candidate.pricing_evidence), evidence_status,
        )

        evidence_component = min(
            1.0,
            weighted_coverage_score
            / 100.0,
        )

        if sentiment_sufficient:
            review_component = min(
                1.0,
                len(
                    usable_reviews
                )
                / 15.0,
            )

        else:
            review_component = min(
                0.30,
                len(
                    usable_reviews
                )
                / 15.0,
            )

        impact_component = min(
            1.0,
            quantified_impacts
            / 3.0,
        )

        pricing_component = float(
            deep.pricing_confidence
            or 0
        )

        candidate.recommendation_confidence = round(
            100
            * (
                0.45
                * evidence_component
                + 0.20
                * review_component
                + 0.20
                * impact_component
                + 0.15
                * pricing_component
            ),
            1,
        )

        first_year = None

        if (
            candidate.annual_software_cost is not None
            and candidate.implementation_cost is not None
        ):
            first_year = (
                float(candidate.annual_software_cost)
                + float(candidate.implementation_cost)
            )

        candidate.budget_score = budget_fit(
            req.budget,
            first_year,
        )

        improvements = self._improvement_scenarios(
            candidate
        )

        candidate.value_assessment = build_value_assessment(
            req.current_annual_process_cost,
            improvements,
            candidate.annual_software_cost,
            candidate.implementation_cost,
            req.budget,
            basis=(
                "Improvement scenarios are derived only from explicitly quantified "
                "customer-impact evidence. ROI/payback remain unavailable without "
                "both a process-cost baseline and verified investment."
                if improvements is not None
                else "No quantified customer-impact evidence was found for this product. "
                "Improvement, benefit, ROI and payback are therefore unavailable rather than assumed."
            ),
        )

        base_score = overall(
            candidate
        )

        confidence_factor = (
            0.85
            + 0.15
            * (
                candidate.recommendation_confidence
                / 100.0
            )
        )

        candidate.final_score = round(
            base_score
            * confidence_factor,
            2,
        )

        return candidate

    def _extract_retained_pricing(self, candidate: ProductCandidate, hits: list[SearchResult], pages: list[dict] | None = None) -> dict:
        """Extract a fixed subscription price only from already-retained evidence."""
        pages_by_url = {(p.get("url") or "").rstrip("/"): p for p in (pages or [])}
        for hit in hits:
            page = pages_by_url.get(hit.url.rstrip("/"), {})
            text = f"{hit.title} {hit.snippet} {self._plain(page.get('content', ''), 12000)}"
            if not self._entity_match(candidate, url=hit.url, title=hit.title, text=text, strict=False):
                continue
            if "contact sales" in text.lower():
                continue
            unit_match = re.search(r"(?i)([£$€]|USD\s*|GBP\s*|EUR\s*)([0-9][0-9,]*(?:\.\d{1,2})?)\s*(?:/|per\s+)(user|seat|location)\s*(?:/|per\s+)(month|mo\.?|year|yr\.?)", text)
            if unit_match:
                symbol = unit_match.group(1).strip().upper()
                currency = {"£": "GBP", "$": "USD", "€": "EUR"}.get(symbol, symbol[:3])
                amount = float(unit_match.group(2).replace(",", ""))
                basis = f"{unit_match.group(1).strip()}{amount:g}/{unit_match.group(3)}/{unit_match.group(4)}"
                evidence = [{"source_url": hit.url, "source_title": hit.title or page.get("title", ""), "evidence_type": "pricing", "claim": basis, "supporting_text": self._plain(page.get("content") or hit.snippet, 500), "source_quality": self._source_quality(hit.url, registrable(candidate.vendor_url)), "confidence": 0.8 if page.get("content") else 0.7, "search_provider": hit.search_provider, "domain": registrable(hit.url), "search_query": hit.query}]
                return {"annual_cost": None, "currency": currency, "basis": basis, "confidence": 0.7, "evidence": evidence}
            match = re.search(r"(?i)([£$€]|USD\s*|GBP\s*|EUR\s*)([0-9][0-9,]*(?:\.\d{1,2})?)\s*(?:/|per\s+)?\s*(month|mo\.?|year|yr\.?|annually|annual)", text)
            if not match:
                continue
            # Unit prices cannot be safely converted into a company subscription.
            tail = text[match.end():match.end() + 35].lower()
            prefix = text[max(0, match.start() - 20):match.start()].lower()
            if "user" in tail or "seat" in tail or "location" in tail or "user" in prefix or "seat" in prefix or "location" in prefix:
                continue
            symbol = match.group(1).strip().upper()
            currency = {"£": "GBP", "$": "USD", "€": "EUR"}.get(symbol, symbol[:3])
            amount = float(match.group(2).replace(",", ""))
            period = match.group(3).lower()
            annual = amount * 12 if period.startswith(("month", "mo")) else amount
            billing_period = "month" if period.startswith(("month", "mo")) else "year"
            basis = f"{match.group(1).strip()}{amount:g}/{billing_period}"
            evidence = [{"source_url": hit.url, "source_title": hit.title or page.get("title", ""), "evidence_type": "pricing", "claim": basis, "supporting_text": self._plain(page.get("content") or hit.snippet, 500), "source_quality": self._source_quality(hit.url, registrable(candidate.vendor_url)), "confidence": 0.8 if page.get("content") else 0.7, "search_provider": hit.search_provider, "domain": registrable(hit.url), "search_query": hit.query}]
            return {"annual_cost": round(annual, 2), "currency": currency, "basis": basis, "confidence": 0.7, "evidence": evidence}
        return {"annual_cost": None, "currency": "GBP", "basis": "", "confidence": 0.0, "evidence": []}

    async def _apply_deep_fallback(self, req: ResearchRequest, candidate: ProductCandidate, bundle: dict, status: str) -> ProductCandidate:
        """Preserve Python-collected evidence when LLM interpretation is unavailable."""
        domain = bundle.get("domain", "")
        candidate.evidence = self._merge_evidence(candidate.evidence, bundle.get("retained_source_evidence", []), limit=35)
        raw_reviews = bundle.get("review_records", [])

        # Deduplicate raw review records by canonical URL / platform
        seen_keys = set()
        deduped_reviews = []
        for r in raw_reviews:
            raw_url = (r.get("source_url") or "").strip().lower().rstrip("/")
            platform = (r.get("platform") or "").strip().lower()
            key = (raw_url, platform)
            if key in seen_keys and raw_url:
                continue
            seen_keys.add(key)
            deduped_reviews.append(r)

        # Deterministically classify review records using standard rules
        for rec in deduped_reviews:
            if rec.get("sentiment") not in {"positive", "neutral", "negative"}:
                self._classify_review_record(rec, candidate.product, domain)
            rec["source_type"] = rec.get("source_type") or (
                "independent_review"
                if any(review_domain in registrable(rec.get("source_url", "")).lower() for review_domain in REVIEW_DOMAINS)
                else "generic_article"
            )
            rec["is_opinion_bearing"] = rec.get("sentiment") in {"positive", "neutral", "negative"}
            rec["is_customer_review"] = bool(rec["is_opinion_bearing"] and rec["source_type"] == "independent_review")
            rec["review_text"] = rec.get("content_excerpt") or rec.get("snippet", "")
            rec["evidence_quote"] = self._plain(rec["review_text"], 420)

        candidate.reviews = deduped_reviews

        classified_reviews = [
            r for r in deduped_reviews
            if r.get("sentiment") in {"positive", "neutral", "negative"}
        ]
        usable_reviews = [
            r for r in classified_reviews
            if self._valid_review_record(r, domain)
        ]
        independent_reviews = [
            r for r in usable_reviews
            if registrable(r["source_url"]).lower() != domain.lower()
        ]
        independent_review_domains = {
            registrable(r["source_url"]).lower()
            for r in independent_reviews
            if registrable(r["source_url"])
        }
        classified_platforms = {
            r["platform"] for r in usable_reviews if r["platform"] != "Web"
        }

        sentiment_sufficient = (
            len(independent_reviews) >= 3
            and len(independent_review_domains) >= 2
        )

        candidate.sentiment_score = self._calculate_sentiment_score(independent_reviews)

        fallback_msg = (
            "Independent review evidence retained and classified deterministically (LLM interpretation unavailable)."
            if sentiment_sufficient
            else (
                "Insufficient independent sentiment evidence."
                if status != "unavailable_due_to_llm_quota"
                else "Independent review evidence retained; sentiment classification unavailable due to LLM quota."
            )
        )

        candidate.sentiment_summary = {
            "score": candidate.sentiment_score,
            "evidence_sufficient": sentiment_sufficient,
            "sentiment_analysis_status": status,
            "analysis_unavailable": status in {
                "unavailable_due_to_llm_quota",
                "partial_llm_failure",
                "partial_truncated_response",
                "missing_from_batch_response",
            },
            "message": fallback_msg,
            "review_evidence_found": len(deduped_reviews),
            "opinion_bearing_reviews_found": len(classified_reviews),
            "positive_themes": [],
            "negative_themes": [],
            "source_count": len(deduped_reviews),
            "classified_review_count": len(usable_reviews),
            "independent_review_count": len(independent_reviews),
            "independent_review_domains": len(independent_review_domains),
            "classified_platform_count": len(classified_platforms),
            "positive_count": sum(r.get("sentiment") == "positive" for r in usable_reviews),
            "neutral_count": sum(r.get("sentiment") == "neutral" for r in usable_reviews),
            "negative_count": sum(r.get("sentiment") == "negative" for r in usable_reviews),
            "target_source_count": 25,
        }

        entity_matched_count = sum(1 for r in deduped_reviews if r.get("classification_reason") != "target_product_not_mentioned")
        independent_count = sum(1 for r in deduped_reviews if registrable(r.get("source_url", "")).lower() != domain.lower())
        opinion_bearing_count = len(classified_reviews)
        insufficient_count = len(deduped_reviews) - len(classified_reviews)
        duplicates_removed_count = len(raw_reviews) - len(deduped_reviews)

        deterministic_count = sum(r.get("classification_method", "").startswith("deterministic") for r in usable_reviews)
        gemini_count = sum(r.get("classification_method") == "gemini_structured" for r in usable_reviews)
        counts = {label: sum(r.get("sentiment") == label for r in usable_reviews) for label in ("positive", "neutral", "negative")}
        logger.info("[SENTIMENT] candidate sources=%s entity matched=%s independent=%s opinion-bearing=%s deterministically classified=%s Gemini classified=%s total classified=%s positive=%s neutral=%s negative=%s independent domains=%s duplicates removed=%s score=%s confidence=%s", len(raw_reviews), entity_matched_count, independent_count, opinion_bearing_count, deterministic_count, gemini_count, len(usable_reviews), counts["positive"], counts["neutral"], counts["negative"], len(independent_review_domains), duplicates_removed_count, candidate.sentiment_score, sentiment_sufficient)
        logger.info(
            "[SENTIMENT_FALLBACK] candidate=%s usable_reviews=%s independent=%s domains=%s score=%s",
            candidate.product,
            len(usable_reviews),
            len(independent_reviews),
            len(independent_review_domains),
            candidate.sentiment_score,
        )
        candidate.customers = self._deterministic_customer_references(
            candidate, bundle.get("general_pages", []), domain
        )[:8]
        candidate.customer_impact = self._deterministic_customer_impacts(
            candidate, bundle.get("general_pages", []), domain
        )
        for customer in candidate.customers:
            source_domain = registrable(customer.get("source_url", "")).lower()
            customer["vendor_name"] = candidate.vendor
            customer["customer_name"] = customer.get("customer", "")
            customer["customer_country"] = ""
            customer["is_explicit_product_use"] = True
            customer["is_independent"] = source_domain != domain.lower()
            customer["evidence_quote"] = customer.get("evidence_text", "")
        independent_customers = sum(
            registrable(row.get("source_url", "")).lower() != domain.lower()
            for row in candidate.customers
        )
        logger.info(
            "[CUSTOMER PIPELINE] product=%s search_results=%s promising_urls=%s selected_urls=%s pages_read=%s pages_with_text=%s named_customers=%s independent_customer_evidence=%s explicit_impacts=%s analysis_status=%s",
            candidate.product,
            (bundle.get("customer_impact_diagnostics") or {}).get("search_results", 0),
            (bundle.get("customer_impact_diagnostics") or {}).get("promising_urls", 0),
            (bundle.get("customer_impact_diagnostics") or {}).get("selected_urls", 0),
            len(bundle.get("general_pages", [])),
            sum(bool(page.get("content")) for page in bundle.get("general_pages", [])),
            len(candidate.customers),
            independent_customers,
            len(candidate.customer_impact),
            "complete" if candidate.customers else f"unknown_no_explicit_customer_evidence_{status}",
        )
        await self._enrich_customer_financials(candidate)
        pricing = self._extract_retained_pricing(
            candidate, bundle.get("evidence_hits", []), bundle.get("general_pages", [])
        )
        candidate.annual_software_cost = pricing["annual_cost"]
        candidate.implementation_cost = None
        candidate.currency = pricing["currency"]
        candidate.pricing_basis = pricing["basis"]
        candidate.pricing_confidence = pricing["confidence"]
        candidate.pricing_evidence = pricing["evidence"]
        if candidate.annual_software_cost is not None and candidate.currency != "GBP":
            converted = await self.fx.convert(candidate.annual_software_cost, candidate.currency, "GBP")
            if converted is not None:
                candidate.annual_software_cost = converted
                candidate.pricing_basis = f"{candidate.pricing_basis} | Converted to GBP in Python using Frankfurter FX."
                candidate.currency = "GBP"
            else:
                # Budget and value calculations use the request's GBP budget; do
                # not compare an unconverted foreign-currency price to it.
                candidate.annual_software_cost = None
        candidate.impact_score = 50.0
        candidate.budget_score = 50.0
        candidate.evidence_coverage = {
            "target": 30, "search_results_found": len(bundle.get("evidence_hits", [])),
            "retained": len(candidate.evidence), "review_sources_found": len(candidate.reviews),
            "review_sources_matched": len(candidate.reviews), "classified_review_count": len(usable_reviews),
            "independent_domains": candidate.sentiment_summary["independent_review_domains"],
            "named_customers": len(candidate.customers), "quantified_impact_claims": len(candidate.customer_impact),
            "independent_customer_evidence": independent_customers,
            "customer_use_evidence_found": len(candidate.customers),
            "customer_use_analysis_status": "complete" if candidate.customers else f"unknown_no_explicit_customer_evidence_{status}",
            "recommendation_status": "VALIDATED" if sentiment_sufficient and candidate.customers else "PROVISIONAL_INSUFFICIENT_EVIDENCE",
            "pricing_sources": len(candidate.pricing_evidence), "deep_analysis_status": "partial",
        }
        discovery = bundle.get("evidence_diagnostics", {})
        review_diagnostics = bundle.get("review_diagnostics", {})
        evidence_status = (
            "FOUND" if usable_reviews and candidate.customers
            else "PARTIAL" if (usable_reviews or candidate.customers or candidate.customer_impact or candidate.pricing_evidence)
            else "UNAVAILABLE" if status == "unavailable_due_to_llm_quota"
            else "CLASSIFICATION_FAILED" if status in {"partial_llm_failure", "partial_truncated_response", "missing_from_batch_response"}
            else "EXTRACTION_FAILED" if bundle.get("collection_error")
            else "NOT_FOUND_AFTER_SEARCH"
        )
        candidate.evidence_coverage.update({
            "queries_attempted": discovery.get("queries_attempted", 0),
            "total_search_results": discovery.get("raw_results", 0),
            "review_platform_results": sum(
                count for source_type, count in discovery.get("source_types_found", {}).items()
                if source_type == "independent_review"
            ),
            "review_candidates": review_diagnostics.get("review_relevant", 0),
            "selected_review_urls": review_diagnostics.get("selected_urls", 0),
            "review_pages_with_text": review_diagnostics.get("pages_with_text", 0),
            "opinion_bearing_reviews": opinion_bearing_count,
            "impact_records": len(candidate.customer_impact),
            "verified_financial_records": len(candidate.pricing_evidence),
            "source_types_found": discovery.get("source_types_found", {}),
            "evidence_status": evidence_status,
            "evidence_unavailable_message": (
                "No classified customer reviews were found after searching the configured product-review, customer-case-study and implementation-source families. No explicit named customer-use evidence was identified. No verified product pricing or financial metrics were available."
                if evidence_status in {"NOT_FOUND_AFTER_SEARCH", "UNAVAILABLE", "EXTRACTION_FAILED", "CLASSIFICATION_FAILED"} else ""
            ),
        })
        logger.info(
            "[RESEARCH EVIDENCE]\nproduct=%s\nqueries_attempted=%s\nsearch_results=%s\nreview_candidates=%s\nselected_review_urls=%s\npages_with_text=%s\nclassified_reviews=%s\nnamed_customers=%s\nexplicit_customer_use=%s\nindependent_customer_use=%s\nimpact_records=%s\nverified_financial_records=%s\nstatus=%s",
            candidate.product, discovery.get("queries_attempted", 0), discovery.get("raw_results", 0),
            review_diagnostics.get("review_relevant", 0), review_diagnostics.get("selected_urls", 0),
            review_diagnostics.get("pages_with_text", 0), len(usable_reviews), len(candidate.customers),
            len(candidate.customers), independent_customers, len(candidate.customer_impact),
            len(candidate.pricing_evidence), evidence_status,
        )
        candidate.final_score = overall(candidate)
        return candidate


    async def _deep_products_batch(
        self,
        req: ResearchRequest,
        candidates: list[ProductCandidate],
        batch_size: int = 1,
    ):
        """Deep-research all validated products with a small number of Gemini calls.

        Search/extraction still happens per product so evidence depth is preserved.
        Gemini interpretation is batched (default two products per request). This keeps
        structured responses comfortably below model output limits while still reducing
        a typical eight-product run from eight deep LLM calls to four.
        """
        bundles = []
        for candidate in candidates:
            try:
                bundles.append(await self._collect_deep_bundle(req, candidate))
            except Exception as exc:
                logger.warning(
                    "Evidence collection failed for %s: %s", candidate.product, exc
                )
                bundles.append({
                    "candidate": candidate,
                    "collection_error": str(exc),
                    "domain": registrable(candidate.vendor_url),
                    "evidence_hits": [],
                    "review_hits": [],
                    "general_pages": [],
                    "review_pages": [],
                    "retained_source_evidence": [],
                    "review_records": [],
                    "evidence_corpus": "",
                    "review_corpus": "",
                })

        enriched = []
        quota_exhausted = False
        batch_failures = []

        # One compact bounded conclusion call per product prevents one response
        # from truncating the analysis for unrelated shortlisted products.
        batch_size = 1
        for offset in range(0, len(bundles), batch_size):
            chunk = bundles[offset: offset + max(1, batch_size)]
            if quota_exhausted:
                for bundle in chunk:
                    enriched.append(await self._apply_deep_fallback(
                        req, bundle["candidate"], bundle,
                        "unavailable_due_to_llm_quota",
                    ))
                continue

            prompt_products = []
            for bundle in chunk:
                candidate = bundle["candidate"]
                prompt_products.append({
                    "product": candidate.product,
                    "vendor": candidate.vendor,
                    **self._build_compact_evidence_pack(bundle),
                })

            prompt = f"""
Perform compact deep evidence analysis for the ONE product below.

Sector: {req.sector}
Business goal: {req.business_goal}
Budget: GBP {req.budget:,.0f}

Use ONLY the source material supplied under that same product. Never transfer
evidence between products. Never invent a URL, review, customer, metric, price,
ROI, feature, implementation claim, or customer relationship.

For every product independently:
1. Classify review/reputation sources only when actual source text supports it.
2. Extract named customers and quantified outcomes only when explicitly supported.
   Customer adoption requires an explicit customer + product/vendor connection.
   Classify customer sources as vendor_case_study, vendor_social,
   customer_authored, independent_article, technographic, or other.
3. Extract numeric recurring/implementation costs only when explicitly supported.
   A deployment scale (stores, locations, users, employees, countries or
   customers served) is context/adoption_scale, NOT a customer impact. Only
   retain an impact when the surrounding evidence explicitly states a change,
   reduction, increase, saving, ROI, payback or measurable improvement.
4. Return conclusions only. Source URLs must be copied exactly from supplied excerpts.
5. Identify evidence-based risks or missing-data uncertainty.
6. If sentiment evidence is weak, set sentiment_evidence_sufficient=false and score 50.
7. Preserve the exact product and vendor names supplied so Python can match results.
8. Keep the JSON COMPACT. Hard limits:
   - review_assessments: max 12
   - customers: max 8
   - impacts: max 8
   - risks: max 6
   - pricing_source_urls: max 4
   Review summaries must be under 30 words. Do not return raw evidence or long text.

PRODUCT EVIDENCE BUNDLES:
{json.dumps(prompt_products)[:70000]}
"""

            logger.info(
                "[3/7] Gemini deep-analysis batch %s-%s of %s products",
                offset + 1,
                min(offset + len(chunk), len(bundles)),
                len(bundles),
            )

            try:
                analysed = await self.gemini.structured(prompt, CompactDeepAnalysis)
            except Exception as exc:
                message = str(exc)
                low = message.lower()
                quota_exhausted = (
                    "429" in low
                    or "resource_exhausted" in low
                    or "quota exceeded" in low
                    or "generaterequestsperdayperprojectpermodel" in low
                    or "free_tier_requests" in low
                )
                # A truncated compact response gets one smaller retry for this
                # product only. It never blocks subsequent products.
                truncated = "truncated" in low or "incomplete" in low or "json_invalid" in low
                if truncated and not quota_exhausted:
                    logger.warning("[DEEP] %s truncated; retrying once with a smaller evidence pack", chunk[0]["candidate"].product)
                    retry_product = {"product": chunk[0]["candidate"].product, "vendor": chunk[0]["candidate"].vendor, **self._build_compact_evidence_pack(chunk[0], compact=True)}
                    try:
                        analysed = await self.gemini.structured(
                            f"Return only compact conclusions with exact supplied source URLs. No raw text. PRODUCT: {json.dumps(retry_product)}",
                            CompactDeepAnalysis,
                        )
                    except Exception as retry_exc:
                        message = str(retry_exc)
                        batch_failures.append(message)
                        logger.warning("[DEEP] compact retry failed for %s: %s", chunk[0]["candidate"].product, retry_exc)
                        enriched.append(await self._apply_deep_fallback(req, chunk[0]["candidate"], chunk[0], "partial_truncated_response"))
                        continue
                else:
                    batch_failures.append(message)
                    logger.warning("Deep-analysis batch failed: %s", exc)
                for bundle in chunk:
                    enriched.append(await self._apply_deep_fallback(
                        req, bundle["candidate"], bundle,
                        "unavailable_due_to_llm_quota" if quota_exhausted else "partial_llm_failure",
                    ))
                continue

            by_key = {
                (item.product.strip().casefold(), item.vendor.strip().casefold()): item
                for item in analysed.products
            }

            for bundle in chunk:
                candidate = bundle["candidate"]
                item = by_key.get(
                    (candidate.product.strip().casefold(), candidate.vendor.strip().casefold())
                )
                if item is None:
                    item = next(
                        (x for x in analysed.products
                         if x.product.strip().casefold() == candidate.product.strip().casefold()),
                        None,
                    )

                if item is None:
                    fallback_cand = await self._apply_deep_fallback(
                        req, candidate, bundle, "missing_from_batch_response"
                    )
                    if fallback_cand.evidence_coverage:
                        fallback_cand.evidence_coverage["deep_analysis_status"] = "missing_from_batch_response"
                    enriched.append(fallback_cand)
                    continue

                deep_data = item.model_dump(exclude={"product", "vendor"})
                allowed_urls = {h.url.rstrip("/") for h in bundle.get("evidence_hits", [])}
                deep_data["pricing_evidence"] = [
                    {
                        "source_url": url,
                        "source_title": "Pricing evidence",
                        "evidence_type": "pricing",
                        "claim": item.pricing_basis or "Explicit pricing evidence",
                        "source_quality": self._source_quality(url, bundle.get("domain", "")),
                        "confidence": 0.7,
                    }
                    for url in item.pricing_source_urls
                    if url.rstrip("/") in allowed_urls
                ]
                deep = DeepProductResearch.model_validate(deep_data)
                candidate = await self._apply_deep_analysis(
                    req, candidate, deep, bundle
                )
                candidate.evidence_coverage["deep_analysis_status"] = "complete"
                enriched.append(candidate)

        self._last_deep_batch_status = {
            "quota_exhausted": quota_exhausted,
            "failures": batch_failures,
            "products_requested": len(candidates),
            "products_fully_analysed": sum(
                1 for c in enriched
                if (c.evidence_coverage or {}).get("deep_analysis_status") == "complete"
            ),
        }
        return enriched


    async def _deep_product(
        self,
        req: ResearchRequest,
        candidate: ProductCandidate,
    ):
        """Compatibility wrapper for one-product deep research."""
        result = await self._deep_products_batch(req, [candidate], batch_size=1)
        return result[0]

    @staticmethod
    def _impact_scope(impact: dict) -> str:
        """Classify scope conservatively; only explicit total OPEX permits translation."""
        metric = str(impact.get("metric") or "").lower()
        claim = str(impact.get("claim") or "").lower()
        app = str(impact.get("application") or "").lower()
        unit = str(impact.get("impact_unit") or "").lower().strip()
        text = f"{metric} {claim} {app}".lower()

        # Check for genuine business outcome indicators
        outcome_indicators = ("reduc", "decreas", "improv", "sav", "faster", "boost", "roi", "payback", "increase", "%", "percent", "min", "hour")
        has_outcome = any(o in text for o in outcome_indicators) or unit in {"%", "gbp", "usd", "eur", "£", "$", "€", "minutes", "hours", "days", "min", "sec", "seconds"}

        # Only classify as adoption_scale when the claim is mere deployment scale without a business outcome
        if not has_outcome:
            scale_terms = ("stores", "locations", "users", "employees", "countries", "clients", "customers", "deployed", "served", "scale", "seats")
            if unit in {"stores", "locations", "users", "employees", "countries", "clients", "customers", "seats"} or any(term in text for term in scale_terms):
                return "adoption_scale"

        if any(term in text for term in ("total operating expenses", "total operating costs", "company-wide operating expenses", "company wide operating expenses")):
            return "total_operating_expenses"
        if any(term in text for term in ("waiting time", "wait time", "queue time", "checkout time", "service time")):
            return "waiting_time"
        if any(term in text for term in ("throughput", "orders per", "transactions per", "speed of service", "transaction speed")):
            return "throughput"
        if any(term in text for term in ("conversion", "sales", "revenue")):
            return "revenue" if "revenue" in text or "sales" in text else "conversion"
        if any(term in text for term in ("satisfaction", "nps", "customer experience", "csat")):
            return "customer_satisfaction"
        if any(term in text for term in ("labour", "labor", "staffing", "wage", "payroll", "labour hours", "labor hours")):
            return "labour_cost"
        if any(term in text for term in ("process", "checkout", "queue", "warehouse", "support", "recruit", "screening")):
            return "process_cost"
        return "other" if text else "unknown"

    async def _customer_financial_context(self, company_name: str) -> dict:
        key = re.sub(r"\s+", " ", (company_name or "").strip().lower())
        if not key:
            return {"status": "unavailable"}
        if key in self._financial_cache:
            logger.info("[FMP] Cache hit: %s", company_name)
            return self._financial_cache[key]
        fmp = await self.fmp.get_financial_context(company_name)
        if fmp.get("status") != "available":
            result = {"status": "unavailable", "provider": "FMP", "reason": fmp.get("status")}
        else:
            result = {
                "status": "available", "provider": "FMP", "symbol": fmp.get("symbol"),
                "operating_expenses": fmp.get("operating_expenses"),
                "currency": fmp.get("currency"), "fiscal_year": fmp.get("fiscal_year"),
                "metrics": fmp.get("metrics", []),
            }
            logger.info("[FMP] Enriched customer: %s", company_name)
        self._financial_cache[key] = result
        return result

    async def _enrich_customer_financials(self, candidate: ProductCandidate) -> None:
        """Attach FMP context without changing adoption/outcome evidence."""
        contexts: dict[str, dict] = {}
        for customer in candidate.customers:
            name = str(customer.get("customer") or "")
            if name:
                contexts[name.lower()] = await self._customer_financial_context(name)
                customer["financial_context"] = contexts[name.lower()]
        for impact in candidate.customer_impact:
            name = str(impact.get("customer") or "")
            context = contexts.get(name.lower()) if name else None
            if context is None and name:
                context = await self._customer_financial_context(name)
            impact["financial_context"] = context or {"status": "unavailable"}
            impact["impact_scope"] = self._impact_scope(impact)
            # Never translate a scoped outcome using total company OPEX.
            impact["financial_translation_status"] = (
                "eligible_only_when_source_explicitly_applies_to_total_opex"
                if impact["impact_scope"] == "total_operating_expenses"
                else "not_computable_without_relevant_cost_base"
            )

    
    async def _company_financials(
        self,
        req: ResearchRequest,
    ):
        if not req.company_name:
            return {
                "status": "not_requested",
                "message": (
                    "No company name supplied. "
                    "Company financial context was not researched."
                ),
                "identity": None,
                "metrics": [],
                "evidence": [],
            }

        # FMP is optional structured enrichment.  A verified high-confidence
        # listed-company match is sufficient financial context; other providers
        # remain the fallback for private/uncovered companies.
        fmp_context = await self.fmp.get_financial_context(
            req.company_name,
            req.company_country,
        )
        if fmp_context.get("status") == "available":
            fmp_identity = fmp_context.get("identity") or {}
            return {
                "status": "verified",
                "message": "Structured financial context retrieved from Financial Modeling Prep.",
                "identity": {
                    "company_name": fmp_context.get("company_name"),
                    "ticker": fmp_context.get("symbol"),
                    "country": fmp_identity.get("country") or req.company_country,
                    "sector": fmp_identity.get("sector"),
                    "industry": fmp_identity.get("industry"),
                    "website": fmp_identity.get("website"),
                    "match_confidence": fmp_identity.get("match_confidence"),
                },
                "metrics": fmp_context.get("metrics", []),
                "evidence": [],
                "fmp": {
                    "status": "available",
                    "provider": "FMP",
                    "symbol": fmp_context.get("symbol"),
                    "company_name": fmp_context.get("company_name"),
                    "operating_expenses": fmp_context.get("operating_expenses"),
                    "currency": fmp_context.get("currency"),
                    "fiscal_year": fmp_context.get("fiscal_year"),
                },
            }

        country = (
            req.company_country
            or ""
        ).lower().strip()

        is_uk = any(
            x in country
            for x in [
                "united kingdom",
                "uk",
                "great britain",
                "britain",
                "england",
                "scotland",
                "wales",
                "northern ireland",
            ]
        )

        is_us = any(
            x in country
            for x in [
                "united states",
                "united states of america",
                "usa",
                "u.s.",
                "america",
            ]
        )

        identity = None
        official_metrics = []
        source_note = ""

        # ----------------------------------------------------
        # COMPANY IDENTITY / OFFICIAL REGISTRY
        # ----------------------------------------------------

        try:
            if is_uk:
                match = await self.ch.search_company(
                    req.company_name
                )

                trading_brand = None
                financial_scope = "legal_entity"

                # Check if Companies House returned ambiguous or no match
                if not match or match.get("status") == "ambiguous":
                    parent_match = None

                    # A. Inspect ambiguous candidates: pick active group / holding / dominant entity if present
                    if match and match.get("status") == "ambiguous":
                        candidates = match.get("candidates", [])
                        active_c = [c for c in candidates if c.get("company_status") == "active"]
                        group_c = [c for c in active_c if any(w in c.get("title", "").lower() for w in ["group", "holdings", "partnership", "plc"])]
                        best_c = (group_c or active_c)[0] if (group_c or active_c) else None
                        if best_c:
                            parent_match = {
                                "company_name": best_c.get("title"),
                                "company_number": best_c.get("company_number"),
                                "similarity": best_c.get("similarity", 0.8),
                                "sic_codes": best_c.get("sic_codes", []),
                                "source_url": f"https://find-and-update.company-information.service.gov.uk/company/{best_c.get('company_number')}",
                            }
                            financial_scope = "group" if group_c else "legal_entity"

                    # B. Try company name variations: Group, Holdings, Limited, UK
                    if not parent_match:
                        for suffix in ["Group", "Holdings", "Limited", "UK"]:
                            alt_match = await self.ch.search_company(f"{req.company_name} {suffix}")
                            if alt_match and alt_match.get("status") != "ambiguous":
                                parent_match = alt_match
                                financial_scope = "group" if suffix in ["Group", "Holdings"] else "legal_entity"
                                break

                    # C. Targeted search for parent company / owning group (e.g. Waitrose -> John Lewis)
                    if not parent_match:
                        try:
                            parent_hits = await self._search_many(
                                [f'"{req.company_name}" UK parent company OR "owned by" OR "group"'],
                                num=5,
                            )
                            for h in parent_hits:
                                text = f"{h.title} {h.snippet}"
                                m = re.search(
                                    r'(?:owned by|subsidiary of|parent company(?: is)?|holding company(?: is)?|part of(?: the)?)\s+([A-Z][A-Za-z0-9\s&,\.\'-]+?(?:plc|limited|ltd|group|holdings|partnership|corporation)?)',
                                    text,
                                    re.I,
                                )
                                if m:
                                    cand_parent = m.group(1).strip(" .,-")
                                    if cand_parent and len(cand_parent) >= 3 and cand_parent.lower() != req.company_name.lower():
                                        alt_match = await self.ch.search_company(cand_parent)
                                        if alt_match and alt_match.get("status") != "ambiguous":
                                            parent_match = alt_match
                                            financial_scope = "parent_company"
                                            break
                        except Exception as p_err:
                            logger.debug("[FINANCE] Parent search error: %s", p_err)

                    if parent_match:
                        match = parent_match
                        trading_brand = req.company_name
                    elif not match:
                        logger.info("[FINANCE] No Companies House registry match for '%s'; falling back to web reports", req.company_name)
                        identity = {
                            "company_name": req.company_name,
                            "country": req.company_country or "United Kingdom",
                            "financial_scope": "legal_entity",
                            "match_confidence": 0.65,
                            "source_url": None,
                        }
                        source_note = (
                            f"Companies House direct registry lookup found no entry for '{req.company_name}'. "
                            "Financial metrics researched via public annual reports and filings."
                        )
                    else:
                        return {
                            "status": "ambiguous_company",
                            "message": (
                                "The company name is ambiguous in Companies House. "
                                "Financials were not attached to avoid matching the wrong organisation."
                            ),
                            "identity": None,
                            "candidates": match.get("candidates", []),
                            "metrics": [],
                            "evidence": [],
                        }

                if match and not identity:
                    cname = match.get("company_name", "")
                    if not financial_scope or financial_scope == "legal_entity":
                        if any(w in cname.lower() for w in ["group", "holdings", "partnership", "plc"]):
                            financial_scope = "group"
                        else:
                            financial_scope = "legal_entity"

                    # For a matched entity that is not already a group/holding/plc, check for an owning group/parent
                    resolved_parent = None
                    if not trading_brand and financial_scope == "legal_entity":
                        try:
                            parent_hits = await self._search_many(
                                [f'"{cname}" parent company OR "owned by" OR "group plc"'],
                                num=4,
                            )
                            for h in parent_hits:
                                text = f"{h.title} {h.snippet}"
                                m = re.search(
                                    r'(?:owned by|subsidiary of|parent company(?: is)?|holding company(?: is)?|part of(?: the)?)\s+([A-Z][A-Za-z0-9&\'\-]+(?:\s+[A-Z][A-Za-z0-9&\'\-]+){0,5})',
                                    text,
                                    re.I,
                                )
                                if m:
                                    raw_p = m.group(1).strip(" .,-")
                                    words = raw_p.split()
                                    cand_p = " ".join(w for w in words if w[0].isupper() or w.lower() in ("plc", "ltd", "limited", "group", "holdings"))
                                    if cand_p and len(cand_p) >= 3 and cand_p.lower() != cname.lower():
                                        resolved_parent = cand_p
                                        trading_brand = req.company_name
                                        break
                        except Exception as p_err:
                            logger.debug("[FINANCE] Matched entity parent search error: %s", p_err)

                    identity = {
                        "company_name": cname,
                        "trading_brand": trading_brand if (trading_brand and trading_brand.lower() != cname.lower()) else None,
                        "financial_scope": "parent_company" if resolved_parent else financial_scope,
                        "parent_company": resolved_parent or (cname if financial_scope in {"parent_company", "group"} and trading_brand else None),
                        "company_number": match.get("company_number"),
                        "country": req.company_country or "United Kingdom",
                        "sic_codes": match.get("sic_codes", []),
                        "source_url": match.get("source_url"),
                        "match_confidence": match.get("similarity", 0.8),
                    }

                    if resolved_parent:
                        source_note = (
                            f"Company identity verified as '{cname}'. Verified owning parent is '{resolved_parent}'. "
                            f"Financial context applies at parent/group reporting level."
                        )
                    elif trading_brand and financial_scope in {"parent_company", "group"}:
                        source_note = (
                            f"Trading brand '{trading_brand}' resolved to {financial_scope} "
                            f"'{cname}' via Companies House. Financial context applies at {financial_scope} level."
                        )
                    else:
                        source_note = (
                            "Company identity verified through Companies House. Detailed financial "
                            "metrics are extracted from annual-report and filing evidence."
                        )

            elif is_us:
                sec = await self.sec.company_facts(
                    req.company_name
                )

                if not sec:
                    logger.info("[FINANCE] No SEC match for '%s'; falling back to web reports", req.company_name)
                    identity = {
                        "company_name": req.company_name,
                        "country": req.company_country or "United States",
                        "financial_scope": "legal_entity",
                        "match_confidence": 0.65,
                        "source_url": None,
                    }
                    source_note = (
                        f"SEC EDGAR direct lookup found no entry for '{req.company_name}'. "
                        "Financial metrics researched via public annual reports and filings."
                    )
                elif sec.get("status") == "ambiguous":
                    return {
                        "status": "ambiguous_company",
                        "message": (
                            "The company name is ambiguous. "
                            "Financials were not attached "
                            "to avoid matching the wrong issuer."
                        ),
                        "identity": None,
                        "candidates": sec.get(
                            "candidates",
                            [],
                        ),
                        "metrics": [],
                        "evidence": [],
                    }
                else:
                    sec_name = sec.get("company_name", "")
                    financial_scope = "group" if any(w in sec_name.lower() for w in ["group", "holdings", "inc", "corp"]) else "legal_entity"
                    identity = {
                        "company_name": sec_name,
                        "ticker": sec.get("ticker"),
                        "cik": sec.get("cik"),
                        "country": req.company_country or "United States",
                        "source_url": sec.get("source_url"),
                        "match_confidence": sec.get("similarity", 0.8),
                        "financial_scope": financial_scope,
                    }

                    for label, metric in (
                        sec.get("metrics")
                        or {}
                    ).items():
                        if (
                            metric
                            and metric.get("value")
                            is not None
                        ):
                            official_metrics.append(
                                {
                                    "metric": label,
                                    "value": metric.get("value"),
                                    "currency": "USD",
                                    "reporting_period": (
                                        metric.get("end")
                                        or (
                                            f'FY{metric.get("fy")}' if metric.get("fy") else None
                                        )
                                    ),
                                    "fiscal_year": metric.get("fy"),
                                    "source": "SEC EDGAR XBRL",
                                    "source_url": sec.get("source_url"),
                                    "tag": metric.get("tag"),
                                    "financial_scope": financial_scope,
                                }
                            )

                    source_note = (
                        "Identity and structured financial metrics "
                        "verified through SEC EDGAR XBRL."
                    )

            else:
                identity = {
                    "company_name": req.company_name,
                    "country": req.company_country or "Global",
                    "financial_scope": "legal_entity",
                    "match_confidence": 0.70,
                    "source_url": None,
                }
                source_note = (
                    f"Official registry lookup is not configured for '{req.company_country or 'this region'}'. "
                    "Financial metrics researched via public annual reports, filings, and investor relations."
                )

        except Exception as exc:
            logger.warning(
                "[FINANCE] Official company registry lookup failed "
                "for %s: %s: %s",
                req.company_name,
                type(exc).__name__,
                exc,
            )

            return {
                "status": "temporarily_unavailable",
                "message": (
                    "Company identity and financial context "
                    "could not be retrieved because the external "
                    "registry service was temporarily unavailable. "
                    "The product research can still continue."
                ),
                "identity": {
                    "company_name": req.company_name,
                    "country": req.company_country,
                },
                "metrics": [],
                "evidence": [],
                "error_type": type(exc).__name__,
            }

        if identity is None:
            return {
                "status": "not_found",
                "message": (
                    "Company identity could not be verified."
                ),
                "identity": None,
                "metrics": [],
                "evidence": [],
            }

        verified_name = (
            identity.get(
                "company_name"
            )
            or req.company_name
        )

        identifier = (
            identity.get(
                "company_number"
            )
            or identity.get(
                "ticker"
            )
            or ""
        )

        # ----------------------------------------------------
        # FINANCIAL EVIDENCE SEARCH
        # ----------------------------------------------------

        # ----------------------------------------------------
        # FINANCIAL EVIDENCE SEARCH
        # ----------------------------------------------------

        queries = [
            f'"{verified_name}" annual report',
            f'"{verified_name}" annual accounts',
            f'"{verified_name}" revenue operating profit annual report',
            f'"{verified_name}" turnover operating profit',
            f'"{verified_name}" staff costs OR employee costs annual report',
            f'"{verified_name}" operating expenses OR operating costs annual report',
        ]
        if is_uk:
            queries.extend([
                f'"{verified_name}" Companies House accounts',
                f'"{verified_name}" UK filed accounts',
            ])
        parent_name = identity.get("parent_company")
        if parent_name:
            queries.extend([
                f'"{parent_name}" annual report "{verified_name}"',
                f'"{parent_name}" annual report segment revenue operating profit',
                f'"{parent_name}" annual accounts turnover operating profit',
            ])

        hits = []

        try:
            hits = await self._search_many(
                queries,
                num=10,
            )

        except Exception as exc:
            logger.warning(
                "[FINANCE] Financial evidence search failed for %s: "
                "%s: %s",
                verified_name,
                type(exc).__name__,
                exc,
            )

        pages = []

        if hits:
            try:
                pages = await self._read_pages(
                    [
                        h.url
                        for h in hits
                    ],
                    12,
                )

            except Exception as exc:
                logger.warning(
                    "[FINANCE] Financial page extraction failed "
                    "for %s: %s: %s",
                    verified_name,
                    type(exc).__name__,
                    exc,
                )

        web_metrics = []
        web_evidence = []
        scope = identity.get("financial_scope", "legal_entity")
        default_curr = "GBP" if is_uk else ("USD" if is_us else "USD")

        # ----------------------------------------------------
        # DETERMINISTIC FINANCIAL EXTRACTION
        # ----------------------------------------------------

        # A. Deterministic extraction from read pages
        for page in pages:
            p_content = page.get("content", "")
            p_url = page.get("url", "")
            p_title = page.get("title", "")
            if p_content:
                extracted = extract_deterministic_metrics(
                    p_content,
                    source_url=p_url,
                    source_title=p_title,
                    financial_scope=scope,
                    company_name=verified_name,
                    default_currency=default_curr,
                )
                web_metrics.extend(extracted)

        # Search snippets are discovery only. Financial metrics require a page
        # that was actually read so magnitude, period and entity can be audited.

        # ----------------------------------------------------
        # BOUNDED GEMINI FINANCIAL EXTRACTION
        # ----------------------------------------------------

        if pages and self.gemini:
            candidate_excerpts = []
            for p in pages:
                candidate_excerpts.extend(
                    find_candidate_excerpts(p.get("content", ""), max_excerpts=4)
                )
            if candidate_excerpts:
                compact_source = "\n---\n".join(candidate_excerpts[:12])
                try:
                    extraction = await self.gemini.structured(
                        f"""Extract only explicitly stated financial metrics for this verified company.
Verified company:
{json.dumps(identity)}

Allowed metrics: revenue, operating_costs, operating_income, adjusted_operating_profit, staff_costs, employees, currency, reporting_period.
Do NOT infer, calculate, or estimate missing figures. Return null if not explicitly reported.
Preserve exact reported numbers and reporting period (e.g. FY2024).

SOURCE EXCERPTS:
{compact_source[:12000]}""",
                        FinancialWebExtraction,
                    )

                    web_evidence = [
                        x.model_dump()
                        for x in extraction.evidence
                    ]

                    for label, canon, val in [
                        ("Revenue", "revenue", extraction.revenue),
                        ("Operating costs", "operating_expenses", extraction.operating_costs),
                        ("Operating income", "operating_income", extraction.operating_income),
                        ("Adjusted operating profit", "operating_income", extraction.adjusted_operating_profit),
                        ("Staff costs", "staff_cost", extraction.staff_costs),
                        ("Profit before tax", "profit_before_tax", extraction.profit_before_tax),
                        ("Net income", "net_income", extraction.net_income),
                        ("Total assets", "total_assets", extraction.total_assets),
                        ("Total liabilities", "total_liabilities", extraction.total_liabilities),
                        ("Cash", "cash", extraction.cash),
                        ("Operating cash flow", "operating_cash_flow", extraction.operating_cash_flow),
                        ("Employees", "employee_count", extraction.employees),
                    ]:
                        if val is None or val == 0:
                            continue

                        source_url = next(
                            (e.source_url for e in extraction.evidence if e.source_url),
                            pages[0].get("url") if pages else None,
                        )

                        metric_period = extraction.reporting_period or next(
                            (parse_reporting_period(p.get("content", ""))[0] for p in pages if parse_reporting_period(p.get("content", ""))[0]),
                            None,
                        )

                        web_metrics.append({
                            "canonical_metric": canon,
                            "reported_label": label,
                            "metric": label,
                            "value": float(val),
                            "currency": "" if label == "Employees" else (extraction.currency or default_curr),
                            "unit": "absolute",
                            "reporting_period": metric_period or None,
                            "fiscal_year": metric_period.replace("FY", "") if metric_period and "FY" in metric_period else None,
                            "financial_scope": scope,
                            "company_name": verified_name,
                            "source": "Annual report / filing web evidence",
                            "source_title": "Official web report / filing",
                            "source_url": source_url,
                            "source_type": "annual_report",
                            "confidence": 0.90,
                            "verified": True,
                        })

                except Exception as exc:
                    logger.warning(
                        "[FINANCE] Gemini financial extraction failed for %s (%s): %s; using deterministic metrics",
                        verified_name,
                        type(exc).__name__,
                        exc,
                    )

        # ----------------------------------------------------
        # MERGE, DEDUPLICATE & PRIORITISE METRICS
        # ----------------------------------------------------

        merged = deduplicate_and_prioritise_metrics(
            official_metrics + web_metrics,
            identity=identity,
        )

        # Assign latest reporting period to identity
        latest_period = next(
            (m.get("reporting_period") for m in merged if m.get("reporting_period")),
            None,
        )
        if latest_period:
            identity["reporting_period"] = latest_period

        # ----------------------------------------------------
        # SECTOR ALIGNMENT
        # ----------------------------------------------------

        sector_alignment = None

        if (
            is_uk
            and identity
        ):
            registry_sector = (
                self._sic_sector_hint(
                    identity.get(
                        "sic_codes"
                    )
                    or []
                )
            )

            if registry_sector:
                requested = (
                    req.sector
                    or ""
                ).lower()

                aligned = (
                    registry_sector.lower()
                    in requested
                    or requested
                    in registry_sector.lower()
                )

                sector_alignment = {
                    "status": (
                        "aligned"
                        if aligned
                        else "mismatch"
                    ),
                    "requested_sector": (
                        req.sector
                    ),
                    "registry_sector_hint": (
                        registry_sector
                    ),
                    "warning": (
                        None
                        if aligned
                        else (
                            f"Company registry activity appears "
                            f"to be {registry_sector}, while the "
                            f"research sector is {req.sector}. "
                            f"Confirm the company/sector "
                            f"combination before relying on "
                            f"the recommendation."
                        )
                    ),
                }

        # ----------------------------------------------------
        # [FINANCIALS] DIAGNOSTIC LOGGING
        # ----------------------------------------------------

        logger.info("[FINANCIALS] input company=%s", req.company_name)
        logger.info("[FINANCIALS] verified entity=%s", verified_name)
        logger.info("[FINANCIALS] company number=%s", identifier)
        logger.info("[FINANCIALS] identity confidence=%.2f", float(identity.get("match_confidence", 1.0)))
        logger.info("[FINANCIALS] official document candidates=%s", len(hits))
        logger.info("[FINANCIALS] readable documents=%s", len(pages))
        logger.info("[FINANCIALS] verified metrics=%s", len(merged))
        for m in merged:
            logger.info(
                "[FINANCIALS] %s=%s %s (label=%s, scope=%s, period=%s)",
                m.get("canonical_metric"),
                m.get("value"),
                m.get("currency"),
                m.get("reported_label"),
                m.get("financial_scope"),
                m.get("reporting_period"),
            )

        # ----------------------------------------------------
        # STATUS & USER EXPLANATION
        # ----------------------------------------------------

        if merged:
            status = "verified"
            message = source_note

        else:
            status = "identity_verified_financials_unavailable"
            dormant_note = " Companies House records indicate this entity files dormant accounts or acts as a holding name." if (is_uk and "dormant" in source_note.lower()) else ""
            parent_note = f" Owning parent is '{identity.get('parent_company')}'." if identity.get("parent_company") else ""
            message = (
                f"{source_note} "
                f"The company identity was verified as '{verified_name}'. "
                f"FMP contained no matching statements.{dormant_note}{parent_note} "
                "Official annual reports and filings were searched, but no defensible financial values "
                "could be verified during this research run."
            )

        fin_res = {
            "status": status,
            "identity": identity,
            "metrics": merged,
            "evidence": web_evidence,
            "sector_alignment": sector_alignment,
            "message": message,
            "company_name": identity.get("company_name") or verified_name,
            "verified_company": verified_name,
            "company_number": identifier,
            "financial_scope": identity.get("financial_scope"),
            "currency": identity.get("currency") or "GBP",
            "reporting_period": identity.get("reporting_period"),
        }

        for m in merged:
            canon = m.get("canonical_metric")
            if canon:
                fin_res[canon] = m.get("value")
                fin_res[f"{canon}_reporting_period"] = m.get("reporting_period")
                fin_res[f"{canon}_source_url"] = m.get("source_url")
                fin_res[f"{canon}_source"] = m.get("source")
                fin_res[f"{canon}_scope"] = m.get("financial_scope")
        if "operating_expenses" in fin_res and "operating_costs" not in fin_res:
            fin_res["operating_costs"] = fin_res["operating_expenses"]
            fin_res["operating_costs_reporting_period"] = fin_res.get("operating_expenses_reporting_period")
            fin_res["operating_costs_source_url"] = fin_res.get("operating_expenses_source_url")

        return fin_res

    async def run(
            self,
            req: ResearchRequest,
        ):
            # =====================================================
            # 0. START
            # =====================================================
            logger.info(
                "[0/9] Research started: "
                "sector=%s goal=%s budget=%s",
                req.sector,
                req.business_goal,
                req.budget,
            )

            # =====================================================
            # 1. BUSINESS PROBLEM UNDERSTANDING
            # =====================================================

            logger.info(
                "[1/9] Understanding business problem"
            )

            understanding = (
                await self._business_understanding(
                    req
                )
            )

            # =====================================================
            # 2. PRODUCT DISCOVERY
            # =====================================================

            logger.info(
                "[2/9] Discovering commercial products"
            )

            (
                seeds,
                discovery_results,
            ) = await self._discover_candidates(
                req,
                understanding,
            )

            # =====================================================
            # 3. PRODUCT VALIDATION
            # =====================================================

            logger.info(
                "[3/9] Validating %s discovered candidates",
                len(
                    seeds
                ),
            )

            candidates = (
                await self._validate_products_batch(
                    req,
                    understanding,
                    seeds,
                )
            )

            if len(candidates) < 5:
                logger.warning(
                    "[DISCOVERY:RECOVERY] Only %s products survived validation; trying bounded product-intent query families.",
                    len(candidates),
                )
                query_families = self._discovery_expansion_queries(req)
                existing = {
                    (registrable(item.vendor_url), self._normalise_entity_text(item.product))
                    for item in candidates
                }
                # Each family is materially different (software/platform versus
                # sector/pricing intent), avoiding repeated article-oriented searches.
                for start in range(0, len(query_families), 4):
                    if len(candidates) >= 5:
                        break
                    recovery_results = await self._search_many(query_families[start:start + 4], num=8)
                    discovery_results = self._merge_search_results(discovery_results, recovery_results)
                    recovery_seeds = self._fallback_candidate_seeds(recovery_results, settings.max_candidates, req)
                    resolved_clues = await asyncio.gather(
                        *(self._resolve_commercial_identity(hit, req) for hit in recovery_results),
                        return_exceptions=True,
                    )
                    recovery_seeds.extend(item for item in resolved_clues if isinstance(item, CandidateSeed))
                    recovery_seeds = self._canonicalise_candidate_seeds(recovery_seeds, settings.max_candidates)
                    recovery_seeds = [seed for seed in recovery_seeds if (registrable(seed.vendor_url), self._normalise_entity_text(seed.product)) not in existing]
                    if not recovery_seeds:
                        continue
                    recovered = await self._validate_products_batch(
                        req,
                        understanding,
                        recovery_seeds,
                    )
                    for item in recovered:
                        key = (registrable(item.vendor_url), self._normalise_entity_text(item.product))
                        if key not in existing:
                            candidates.append(item)
                            existing.add(key)

            if not candidates:
                logger.warning(
                    "[RESEARCH] No defensible commercial products could be validated; returning an empty controlled result."
                )
                return {
                    "business_problem": understanding.model_dump(),
                    "preliminary_ranking": [],
                    "recommendations": [],
                    "validated_products": [],
                    "company_financial_context": {"status": "not_researched"},
                    "research_status": "no_defensible_products",
                    "message": "No defensible commercial products could be validated from the available vendor evidence.",
                    "data_quality": {
                        "search_result_count": len(discovery_results),
                        "candidate_count_discovered": len(seeds),
                        "validated_count": 0,
                        "deep_research_count": 0,
                        "recommended_count": 0,
                        "research_complete": True,
                    },
                }

            logger.info(
                "[3/9] %s commercial products validated",
                len(
                    candidates
                ),
            )

            # =====================================================
            # 4. PRELIMINARY RANKING
            # =====================================================
            #
            # IMPORTANT:
            #
            # Do NOT pretend that sentiment/customer impact/
            # pricing exist yet.
            #
            # Preliminary ranking decides WHICH products receive
            # expensive deep research.
            # =====================================================

            # Enforce uniqueness of validated candidates by domain and product
            seen_cand_keys = set()
            unique_cands = []
            for c in candidates:
                d_key = registrable(c.vendor_url).lower()
                p_key = self._normalise_entity_text(c.product)
                k = (d_key or self._normalise_entity_text(c.vendor), p_key)
                if k in seen_cand_keys:
                    continue
                seen_cand_keys.add(k)
                unique_cands.append(c)
            candidates = unique_cands

            for candidate in candidates:

                candidate.sentiment_score = 50.0
                candidate.impact_score = 50.0
                candidate.budget_score = 50.0

                candidate.final_score = (
                    self._preliminary_score(
                        candidate
                    )
                )

            candidates.sort(
                key=lambda item: (
                    item.final_score
                ),
                reverse=True,
            )

            # Deep research only the strongest validated products.
            #
            # Maximum = 5.
            #
            # If fewer than 5 products validated,
            # research all of them.

            deep_limit = min(
                5,
                len(
                    candidates
                ),
            )

            shortlisted = (
                candidates[
                    :deep_limit
                ]
            )

            logger.info(
                "[4/9] Preliminary ranking complete. "
                "%s products selected for deep research",
                len(
                    shortlisted
                ),
            )

            preliminary_ranking = []

            for index, candidate in enumerate(
                candidates,
                1,
            ):
                preliminary_ranking.append(
                    {
                        "rank": index,
                        "product": (
                            candidate.product
                        ),
                        "vendor": (
                            candidate.vendor
                        ),
                        "vendor_url": (
                            candidate.vendor_url
                        ),
                        "preliminary_score": (
                            candidate.final_score
                        ),
                        "deep_research_selected": (
                            candidate
                            in shortlisted
                        ),
                    }
                )

            # =====================================================
            # 5. DEEP RESEARCH ON SHORTLIST ONLY
            # =====================================================
            #
            # This performs:
            #
            # - detailed evidence
            # - independent evidence
            # - sentiment/reviews
            # - customer adoption
            # - quantified customer impact
            # - pricing
            # - implementation risk
            #
            # Do ONE PRODUCT PER GEMINI STRUCTURED CALL.
            # =====================================================

            logger.info(
                "[5/9] Deep evidence, sentiment, customer, "
                "impact and pricing research for %s products",
                len(
                    shortlisted
                ),
            )

            enriched = (
                await self._deep_products_batch(
                    req,
                    shortlisted,
                    batch_size=1,
                )
            )

            # =====================================================
            # 6. FINAL PRODUCT RANKING
            # =====================================================
            #
            # overall() can now use:
            #
            # goal
            # sector
            # evidence
            # adoption
            # momentum
            # pricing/budget
            # sentiment
            # customer impact
            # implementation
            #
            # Missing dimensions are automatically omitted
            # and weights renormalised by scoring.py.
            # =====================================================

            for candidate in enriched:
                # _apply_deep_analysis() already applies the recommendation-
                # confidence adjustment. Only calculate a plain score when a
                # deep-analysis fallback left no usable final score.
                if not candidate.final_score:
                    candidate.final_score = overall(
                        candidate
                    )

            # Final canonical deduplication to ensure unique vendor/product recommendations
            unique_enriched = []
            seen_final_keys = set()
            for cand in enriched:
                d_key = registrable(cand.vendor_url).lower()
                p_key = self._normalise_entity_text(cand.product)
                v_key = self._normalise_entity_text(cand.vendor)
                final_key = (d_key or v_key, p_key)
                if final_key in seen_final_keys:
                    continue
                seen_final_keys.add(final_key)
                unique_enriched.append(cand)
            enriched = unique_enriched

            # A final recommendation must have a public numeric commercial-cost
            # signal.  "Contact sales" and empty pricing sections are not cost
            # evidence and therefore cannot pass this gate.
            financially_eligible = []
            for cand in enriched:
                numeric_public_price = cand.annual_software_cost is not None
                if not numeric_public_price:
                    numeric_public_price = any(
                        re.search(r"(?:[£$€]|\b(?:GBP|USD|EUR)\b)\s*\d", str(item.get("claim", "")), re.I)
                        for item in (cand.pricing_evidence or [])
                        if isinstance(item, dict)
                    )
                if not numeric_public_price:
                    logger.info(
                        "[ELIGIBILITY] product rejected: insufficient public financial/commercial data product=%s",
                        cand.product,
                    )
                    continue
                financially_eligible.append(cand)
            enriched = financially_eligible

            enriched.sort(
                key=lambda item: (
                    item.final_score
                ),
                reverse=True,
            )

            recommendation_limit = min(
                5,
                len(
                    enriched
                ),
            )

            recommendations = (
                enriched[
                    :recommendation_limit
                ]
            )

            for rank, candidate in enumerate(
                recommendations,
                1,
            ):
                candidate.rank = rank

            logger.info(
                "[6/9] Final product ranking complete. "
                "%s recommendations retained",
                len(
                    recommendations
                ),
            )
            logger.info("[ELIGIBILITY] financially_eligible=%s", len(enriched))

            # =====================================================
            # 7. USER COMPANY FINANCIAL RESEARCH
            # =====================================================

            logger.info(
                "[7/9] Researching user company identity "
                "and financial context"
            )

            financials = (
                await self._company_financials(
                    req
                )
            )

            # =====================================================
            # 8. PREDICTED ROI FOR EACH RECOMMENDATION
            # =====================================================
            #
            # Product evidence tells us:
            #
            # - actual customer financial impact
            # - software cost
            # - implementation cost
            #
            # User-company research gives us:
            #
            # - company financial context
            # - operating-cost context
            #
            # If the user supplied current_annual_process_cost,
            # it takes priority because it is the relevant
            # business-process baseline.
            #
            # This is predicted ROI.
            #
            # Realised ROI is measured later by Impact Tracker.
            # =====================================================

            logger.info(
                "[8/9] Building predicted ROI cases"
            )

            for candidate in recommendations:

                candidate = (
                    self._apply_user_company_roi(
                        req,
                        candidate,
                        financials,
                    )
                )

            # =====================================================
            # DATA QUALITY COUNTS
            # =====================================================

            all_evidence = sum(
                len(
                    candidate.evidence
                    or []
                )
                for candidate in recommendations
            )

            all_reviews = sum(
                len(
                    candidate.reviews
                    or []
                )
                for candidate in recommendations
            )

            all_classified_reviews = sum(
                int(
                    (
                        candidate.sentiment_summary
                        or {}
                    ).get(
                        "classified_review_count",
                        0,
                    )
                    or 0
                )
                for candidate in recommendations
            )

            all_customers = sum(
                len(
                    candidate.customers
                    or []
                )
                for candidate in recommendations
            )

            all_impacts = sum(
                1
                for candidate in recommendations
                for impact in (
                    candidate.customer_impact
                    or []
                )
                if (
                    isinstance(
                        impact,
                        dict,
                    )
                    and isinstance(
                        impact.get(
                            "impact_value"
                        ),
                        (
                            int,
                            float,
                        ),
                    )
                )
            )

            all_pricing = sum(
                len(
                    candidate.pricing_evidence
                    or []
                )
                for candidate in recommendations
            )

            predicted_roi_count = sum(
                1
                for candidate in recommendations
                if (
                    candidate.value_assessment
                    or {}
                ).get(
                    "expected_roi_percent"
                )
                is not None
            )

            # =====================================================
            # RETAIN VALIDATED PRODUCTS
            # =====================================================

            deep_urls = {
                candidate.vendor_url
                for candidate
                in shortlisted
            }

            validated_products = []

            for candidate in candidates:

                row = (
                    candidate.model_dump()
                )

                row[
                    "research_depth"
                ] = (
                    "deep"
                    if candidate.vendor_url
                    in deep_urls
                    else "validated_only"
                )

                validated_products.append(
                    row
                )

            # =====================================================
            # FINISHED
            # =====================================================

            logger.info(
                "[9/9] Research complete"
            )

            return {
                "business_problem": (
                    understanding.model_dump()
                ),

                "preliminary_ranking": (
                    preliminary_ranking
                ),

                "recommendations": [
                    candidate.model_dump()
                    for candidate
                    in recommendations
                ],

                "validated_products": (
                    validated_products
                ),

                "company_financial_context": (
                    financials
                ),

                "methodology": {
                    "business_understanding": (
                        "Gemini converts the user's sector, goal, "
                        "company size and business context into "
                        "processes, capabilities, KPIs and commercial "
                        "software search queries."
                    ),

                    "discovery": (
                        "Serper discovers current commercial products "
                        "from live web search results."
                    ),

                    "validation": (
                        "Products are retained only when the vendor, "
                        "product identity and relevance can be validated "
                        "against available evidence."
                    ),

                    "preliminary_ranking": (
                        "Validated products are preliminarily ranked "
                        "using goal fit, sector fit, evidence, adoption, "
                        "momentum and implementation feasibility. "
                        "Sentiment, detailed customer impact and pricing "
                        "are intentionally excluded at this stage."
                    ),

                    "shortlisting": (
                        "Only the five strongest validated products "
                        "receive expensive deep research."
                    ),

                    "deep_research": (
                        "Each shortlisted product is researched "
                        "individually for evidence, independent reviews, "
                        "sentiment, named customers, quantified customer "
                        "impact, pricing, implementation and risks."
                    ),

                    "final_ranking": (
                        "Python recalculates the final evidence-aware "
                        "ranking after deep research. Missing evidence "
                        "dimensions are excluded rather than represented "
                        "as artificial neutral performance."
                    ),

                    "customer_impact": (
                        "Named customer adoption is kept separate from "
                        "quantified impact. A company merely using a "
                        "product does not prove financial benefit."
                    ),

                    "roi_prediction": (
                        "Pre-implementation ROI uses verified software "
                        "cost, implementation cost, directly quantified "
                        "financial customer-impact evidence and a relevant "
                        "user-company process-cost baseline."
                    ),

                    "financial_data": (
                        "Financial Modeling Prep (FMP) is optional structured "
                        "financial enrichment for listed companies, including "
                        "operating expenses and revenue context. Company-wide "
                        "operating expenses are treated as financial context and "
                        "are not automatically used as the ROI baseline for "
                        "process-specific AI/software implementations."
                    ),

                    "impact_tracking": (
                        "Predicted ROI is separate from realised ROI. "
                        "After implementation, actual KPI and financial "
                        "measurements are stored by the Impact Tracker."
                    ),

                    "missing_data": (
                        "Missing pricing, financial impact, process cost "
                        "or company financial evidence remains unavailable "
                        "rather than being invented."
                    ),
                },

                "data_quality": {
                    "search_result_count": len(
                        discovery_results
                    ),

                    "candidate_count_discovered": len(
                        seeds
                    ),

                    "validated_count": len(
                        candidates
                    ),

                    "deep_research_count": len(
                        shortlisted
                    ),

                    "recommended_count": len(
                        recommendations
                    ),

                    "retained_product_evidence": (
                        all_evidence
                    ),

                    "retained_review_sources": (
                        all_reviews
                    ),

                    "classified_review_sources": (
                        all_classified_reviews
                    ),

                    "named_customer_records": (
                        all_customers
                    ),

                    "quantified_customer_impacts": (
                        all_impacts
                    ),

                    "pricing_evidence_sources": (
                        all_pricing
                    ),

                    "predicted_roi_available_for": (
                        predicted_roi_count
                    ),

                    "research_complete": (
                        getattr(
                            self,
                            "_last_deep_batch_status",
                            {},
                        ).get(
                            "products_fully_analysed",
                            0,
                        )
                        == len(
                            shortlisted
                        )
                    ),

                    "products_fully_analysed": (
                        getattr(
                            self,
                            "_last_deep_batch_status",
                            {},
                        ).get(
                            "products_fully_analysed",
                            0,
                        )
                    ),
                },
            }


    def _improvement_scenarios(
        self,
        candidate: ProductCandidate,
    ) -> tuple[float, float, float] | None:
        """
        Build conservative, expected and optimistic financial
        improvement scenarios from verified customer-impact evidence.

        Only percentage-based financial/cost reductions are accepted.

        Operational improvements such as waiting-time reduction,
        throughput improvement, conversion uplift or CSAT improvement
        are NOT automatically treated as financial cost reductions.

        Returns:
            (conservative, expected, optimistic)

        or:
            None
        """

        values: list[float] = []

        financial_terms = (
            "cost reduction",
            "cost reductions",
            "cost saving",
            "cost savings",
            "operating cost",
            "operating costs",
            "operating expense",
            "operating expenses",
            "opex",
            "labour cost",
            "labour costs",
            "labor cost",
            "labor costs",
            "staff cost",
            "staff costs",
            "staffing cost",
            "staffing costs",
            "expense reduction",
            "expense reductions",
            "financial saving",
            "financial savings",
        )

        for impact in candidate.customer_impact or []:
            if not isinstance(impact, dict):
                continue

            value = impact.get("impact_value")

            if not isinstance(value, (int, float)):
                continue

            value = float(value)

            if value <= 0 or value > 100:
                continue

            unit = str(
                impact.get("impact_unit")
                or ""
            ).lower()

            # Financial improvement scenarios must be percentages.
            if (
                "%" not in unit
                and "percent" not in unit
                and "percentage" not in unit
            ):
                continue

            text = " ".join(
                [
                    str(
                        impact.get("metric")
                        or ""
                    ),
                    str(
                        impact.get("claim")
                        or ""
                    ),
                    str(
                        impact.get("application")
                        or ""
                    ),
                ]
            ).lower()

            if not any(
                term in text
                for term in financial_terms
            ):
                continue

            values.append(value)

        if not values:
            return None

        expected = float(
            statistics.median(values)
        )

        conservative = max(
            0.0,
            expected * 0.60,
        )

        optimistic = min(
            100.0,
            expected * 1.25,
        )

        return (
            round(conservative, 2),
            round(expected, 2),
            round(optimistic, 2),
        )

    @staticmethod
    def _preliminary_score(
        candidate: ProductCandidate,
    ) -> float:
        """
        Preliminary ranking BEFORE deep research.

        At this point we deliberately do NOT use:
        - sentiment
        - customer impact
        - detailed pricing
        - ROI

        Those dimensions have not been researched yet.

        The purpose of this score is only to decide
        which validated products deserve expensive
        deep research.
        """

        weights = {
            "goal_fit": 0.28,
            "sector_fit": 0.20,
            "evidence_score": 0.18,
            "adoption_score": 0.12,
            "momentum_score": 0.08,
            "implementation_score": 0.14,
        }

        total = 0.0

        for field, weight in weights.items():
            try:
                value = float(
                    getattr(
                        candidate,
                        field,
                        0,
                    )
                    or 0
                )
            except (TypeError, ValueError):
                value = 0.0

            value = max(
                0.0,
                min(
                    100.0,
                    value,
                ),
            )

            total += value * weight

        return round(total, 2)


    @staticmethod
    def _company_metric_value(
            financials: dict,
            metric_names: tuple[str, ...],
        ) -> float | None:
            """
            Find one numeric company financial metric.

            Example:
            metric_names=(
                "Operating costs",
                "Operating expenses",
            )
            """

            if not isinstance(
                financials,
                dict,
            ):
                return None

            metrics = (
                financials.get(
                    "metrics"
                )
                or []
            )

            wanted = {
                str(x).lower().strip()
                for x in metric_names
            }

            for row in metrics:
                if not isinstance(
                    row,
                    dict,
                ):
                    continue

                name = str(
                    row.get(
                        "metric"
                    )
                    or ""
                ).lower().strip()

                if name not in wanted:
                    continue

                value = row.get(
                    "value"
                )

                if value is None:
                    continue

                try:
                    value = float(
                        str(value)
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    continue

                if value > 0:
                    return value

            return None


    @staticmethod
    def _goal_allows_total_opex_baseline(
            business_goal: str,
        ) -> bool:
            """
            Total company operating expenses must NOT normally
            be used as the ROI baseline.

            It is only reasonable when the user's stated goal
            explicitly concerns broad operating-cost reduction.

            Example allowed:
                "Reduce company-wide operating expenses"

            Example NOT allowed:
                "Reduce checkout waiting time"
            """

            goal = str(
                business_goal
                or ""
            ).lower()

            broad_cost_terms = (
                "operating expenses",
                "operating expense",
                "operating costs",
                "operating cost",
                "opex",
                "company-wide costs",
                "company wide costs",
                "overall operating cost",
                "overall operating expense",
            )

            return any(
                term in goal
                for term in broad_cost_terms
            )


    def _roi_baseline(
            self,
            req: ResearchRequest,
            financials: dict,
        ) -> tuple[
            float | None,
            str,
        ]:
            """
            Decide which cost baseline may safely be used
            for predicted ROI.

            Priority:

            1. User-supplied relevant annual process cost.
            2. Company-wide OPEX only when the goal explicitly
               concerns broad OPEX reduction.
            3. Otherwise no financial baseline.
            """

            if (
                req.current_annual_process_cost
                is not None
                and req.current_annual_process_cost > 0
            ):
                return (
                    float(
                        req.current_annual_process_cost
                    ),
                    "user_supplied_relevant_process_cost",
                )

            operating_costs = (
                self._company_metric_value(
                    financials,
                    (
                        "Operating costs",
                        "Operating expenses",
                        "Operating expense",
                    ),
                )
            )

            if (
                operating_costs is not None
                and self._goal_allows_total_opex_baseline(
                    req.business_goal
                )
            ):
                return (
                    operating_costs,
                    "verified_company_operating_costs",
                )

            return (
                None,
                "relevant_process_cost_unavailable",
            )


    def _apply_user_company_roi(
            self,
            req: ResearchRequest,
            candidate: ProductCandidate,
            financials: dict,
        ) -> ProductCandidate:
            """
            Build predicted ROI AFTER:

            - product recommendation research
            - pricing research
            - customer-impact research
            - user-company financial research

            This is PRE-IMPLEMENTATION predicted ROI.

            It is deliberately separate from realised ROI
            recorded later by the Impact Tracker.
            """

            improvements = (
                self._improvement_scenarios(
                    candidate
                )
            )

            (
                baseline_cost,
                baseline_source,
            ) = self._roi_baseline(
                req,
                financials,
            )

            assessment = (
                build_value_assessment(
                    baseline_cost,
                    improvements,
                    candidate.annual_software_cost,
                    candidate.implementation_cost,
                    req.budget,
                    basis=(
                        "Predicted ROI uses verified software pricing, "
                        "verified quantified financial customer-impact "
                        "evidence and the user's relevant process-cost "
                        "baseline. Total company operating expenses are "
                        "used only when the stated business goal explicitly "
                        "targets company-wide operating expenditure."
                    ),
                )
            )

            assessment[
                "baseline_source"
            ] = baseline_source

            assessment[
                "prediction_type"
            ] = "pre_implementation_predicted_roi"

            assessment[
                "company_financial_status"
            ] = (
                financials.get(
                    "status"
                )
                if isinstance(
                    financials,
                    dict,
                )
                else "unavailable"
            )

            assessment[
                "company_identity"
            ] = (
                financials.get(
                    "identity"
                )
                if isinstance(
                    financials,
                    dict,
                )
                else None
            )

            assessment[
                "operating_cost_context"
            ] = self._company_metric_value(
                financials,
                (
                    "Operating costs",
                    "Operating expenses",
                    "Operating expense",
                ),
            )

            assessment[
                "roi_available"
            ] = (
                assessment.get(
                    "expected_roi_percent"
                )
                is not None
            )

            if improvements is None:
                assessment[
                    "unavailable_reason"
                ] = (
                    "No directly quantified financial cost-reduction "
                    "evidence was found from customers using this product."
                )

            elif baseline_cost is None:
                assessment[
                    "unavailable_reason"
                ] = (
                    "The relevant annual process cost is unavailable. "
                    "Total company operating expenses cannot safely be "
                    "used for this specific business process."
                )

            elif (
                candidate.annual_software_cost
                is None
                or candidate.implementation_cost
                is None
            ):
                assessment[
                    "unavailable_reason"
                ] = (
                    "Complete first-year investment is unavailable. "
                    "Both annual software cost and implementation cost "
                    "are required for ROI."
                )

            else:
                assessment[
                    "unavailable_reason"
                ] = None

            candidate.value_assessment = (
                assessment
            )

            return candidate
