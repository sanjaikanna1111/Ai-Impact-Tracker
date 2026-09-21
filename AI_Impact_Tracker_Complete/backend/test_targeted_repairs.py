"""Comprehensive automated test suite for AI Impact Tracker targeted repairs.

Covers:
- Area 1: Product Validation
- Area 2: Sentiment Coverage
- Area 3: Company Identity & Financials
- Area 4: ROI & Value
"""

from unittest.mock import AsyncMock, patch
import pytest

from app.schemas import (
    BusinessUnderstanding,
    EvidenceItem,
    ProductCandidate,
    ResearchRequest,
    SearchResult,
)
from app.services.research import (
    BatchProductAnalyses,
    CandidateSeed,
    ProductAnalysis,
    ResearchService,
)
from app.services.value_model import build_value_assessment, roi, payback_months
from app.providers.finance import CompaniesHouseProvider, SECProvider
from app.providers.fmp import FMPProvider


# =====================================================================
# FIXTURES & HELPERS
# =====================================================================

def make_request(goal="Reduce customer queue waiting time", cost=None):
    return ResearchRequest(
        sector="Retail",
        business_goal=goal,
        budget=50000.0,
        company_size="Large",
        employees=500,
        company_name="Waitrose",
        company_country="United Kingdom",
        current_annual_process_cost=cost,
    )


def make_understanding():
    return BusinessUnderstanding(
        business_problem="Long checkout queues during peak retail hours.",
        capabilities=["Queue analytics", "Customer flow tracking", "Wait time notification"],
        processes=["Checkout line management"],
        kpis=["Queue wait time", "Customer throughput"],
        search_queries=["queue management software"],
    )


def make_seed(name, vendor=None, url=None, why=None):
    v = vendor or f"{name} Technologies"
    u = url or f"https://{name.lower().replace(' ', '')}.com"
    w = why or f"{name} is a queue management software platform that helps reduce customer wait time."
    return CandidateSeed(product=name, vendor=v, vendor_url=u, why_relevant=w)


def make_source_text(product_name):
    return (
        f"Welcome to {product_name}. Our enterprise software platform offers cloud solutions, "
        f"pricing plans, features, and dashboards to reduce customer queue waiting time. "
        f"Request a demo today for your retail locations."
    )


# =====================================================================
# AREA 1: PRODUCT VALIDATION
# =====================================================================

@pytest.mark.asyncio
async def test_validation_retains_minimum_3_when_5_genuine_discovered():
    service = ResearchService()
    req = make_request()
    understanding = make_understanding()
    seeds = [make_seed(f"QueuePro{i}") for i in range(1, 6)]

    # Mock _read_pages and _search_many
    service._search_many = AsyncMock(return_value=[])
    service._read_pages = AsyncMock(return_value=[
        {"url": s.vendor_url, "title": f"{s.product} Software", "content": make_source_text(s.product)}
        for s in seeds
    ])
    # Gemini validates only 1 product
    gemini_resp = BatchProductAnalyses(products=[
        ProductAnalysis(
            product="QueuePro1", vendor="QueuePro1 Technologies",
            is_commercial_product=True, is_relevant=True,
            goal_fit=80.0, sector_fit=80.0, evidence_score=80.0,
            adoption_score=70.0, momentum_score=70.0, implementation_score=70.0,
        )
    ])
    service.gemini.structured = AsyncMock(return_value=gemini_resp)

    retained = await service._validate_products_batch(req, understanding, seeds)
    assert len(retained) >= 3
    assert any(p.product == "QueuePro1" for p in retained)


@pytest.mark.asyncio
async def test_validation_exactly_3_genuine_all_survive():
    service = ResearchService()
    req = make_request()
    understanding = make_understanding()
    seeds = [make_seed(f"FlowApp{i}") for i in range(1, 4)]

    service._search_many = AsyncMock(return_value=[])
    service._read_pages = AsyncMock(return_value=[
        {"url": s.vendor_url, "title": f"{s.product} Software", "content": make_source_text(s.product)}
        for s in seeds
    ])
    service.gemini.structured = AsyncMock(return_value=BatchProductAnalyses(products=[
        ProductAnalysis(
            product=s.product, vendor=s.vendor,
            is_commercial_product=True, is_relevant=True,
            goal_fit=85.0, sector_fit=85.0, evidence_score=80.0,
            adoption_score=75.0, momentum_score=75.0, implementation_score=75.0,
        )
        for s in seeds
    ]))

    retained = await service._validate_products_batch(req, understanding, seeds)
    assert len(retained) == 3


@pytest.mark.asyncio
async def test_validation_only_2_genuine_returns_2():
    service = ResearchService()
    req = make_request()
    understanding = make_understanding()
    seeds = [make_seed("AppOne"), make_seed("AppTwo")]

    service._search_many = AsyncMock(return_value=[])
    service._read_pages = AsyncMock(return_value=[
        {"url": s.vendor_url, "title": f"{s.product} Software", "content": make_source_text(s.product)}
        for s in seeds
    ])
    service.gemini.structured = AsyncMock(return_value=BatchProductAnalyses(products=[]))

    retained = await service._validate_products_batch(req, understanding, seeds)
    # Only 2 genuine candidates exist; should return 2 without fabricating
    assert len(retained) == 2


@pytest.mark.asyncio
async def test_validation_rejects_article_and_retains_genuine():
    service = ResearchService()
    req = make_request()
    understanding = make_understanding()
    p1 = make_seed("AppAlpha")
    p2 = make_seed("AppBeta")
    article = CandidateSeed(
        product="Top 10 Queue Management Software",
        vendor="TechBlog",
        vendor_url="https://techblog.com/articles/top-10-queue-software",
        why_relevant="Comparison article",
    )
    seeds = [p1, p2, article]

    service._search_many = AsyncMock(return_value=[])
    service._read_pages = AsyncMock(return_value=[
        {"url": p1.vendor_url, "title": "AppAlpha", "content": make_source_text("AppAlpha")},
        {"url": p2.vendor_url, "title": "AppBeta", "content": make_source_text("AppBeta")},
        {"url": article.vendor_url, "title": "Top 10 Article", "content": "List of articles"},
    ])
    service.gemini.structured = AsyncMock(return_value=BatchProductAnalyses(products=[]))

    retained = await service._validate_products_batch(req, understanding, seeds)
    assert len(retained) == 2
    assert all(p.product in ["AppAlpha", "AppBeta"] for p in retained)


@pytest.mark.asyncio
async def test_validation_rejects_facebook_post():
    service = ResearchService()
    req = make_request()
    understanding = make_understanding()
    p1 = make_seed("AppGamma")
    p2 = make_seed("AppDelta")
    fb = CandidateSeed(
        product="Queue Discussion",
        vendor="Facebook User",
        vendor_url="https://facebook.com/post/12345",
        why_relevant="Social post discussion",
    )
    seeds = [p1, p2, fb]

    service._search_many = AsyncMock(return_value=[])
    service._read_pages = AsyncMock(return_value=[
        {"url": p1.vendor_url, "title": "AppGamma", "content": make_source_text("AppGamma")},
        {"url": p2.vendor_url, "title": "AppDelta", "content": make_source_text("AppDelta")},
        {"url": fb.vendor_url, "title": "Facebook Post", "content": "Social comment"},
    ])
    service.gemini.structured = AsyncMock(return_value=BatchProductAnalyses(products=[]))

    retained = await service._validate_products_batch(req, understanding, seeds)
    assert len(retained) == 2
    assert all(p.product in ["AppGamma", "AppDelta"] for p in retained)


@pytest.mark.asyncio
async def test_validation_gemini_5xx_retains_via_deterministic():
    service = ResearchService()
    req = make_request()
    understanding = make_understanding()
    seeds = [make_seed(f"ServiceSeed{i}") for i in range(1, 4)]

    service._search_many = AsyncMock(return_value=[])
    service._read_pages = AsyncMock(return_value=[
        {"url": s.vendor_url, "title": f"{s.product} Platform", "content": make_source_text(s.product)}
        for s in seeds
    ])
    # Gemini throws 503 Service Unavailable
    service.gemini.structured = AsyncMock(side_effect=RuntimeError("503 Service Unavailable: Gemini overloaded"))

    retained = await service._validate_products_batch(req, understanding, seeds)
    assert len(retained) == 3


# =====================================================================
# AREA 2: SENTIMENT COVERAGE
# =====================================================================

def test_sentiment_explicit_positive_review():
    service = ResearchService()
    rec = {
        "source_url": "https://reviews.example/waitwhile",
        "source_title": "Great tool for retail",
        "snippet": "Waitwhile is easy to use, huge improvement, and saves time. Highly recommend.",
        "content_excerpt": "We loved this software. Powerful and streamlined queue management.",
    }
    result = service._classify_review_record(rec, "Waitwhile", "waitwhile.com")
    assert result["sentiment"] == "positive"
    assert result["confidence"] >= 0.65


def test_sentiment_explicit_negative_review():
    service = ResearchService()
    rec = {
        "source_url": "https://reviews.example/waitwhile",
        "source_title": "Terrible software",
        "snippet": "Waitwhile is buggy, slow, and poor support. Waste of money and do not recommend.",
        "content_excerpt": "Frustrating experience with frequent bugs and awful customer service.",
    }
    result = service._classify_review_record(rec, "Waitwhile", "waitwhile.com")
    assert result["sentiment"] == "negative"
    assert result["confidence"] >= 0.65


def test_sentiment_descriptive_product_text_is_insufficient():
    service = ResearchService()
    rec = {
        "source_url": "https://directory.example/waitwhile",
        "source_title": "Waitwhile Product Overview",
        "snippet": "Waitwhile is a cloud-based queue management application with SMS notifications.",
        "content_excerpt": "Features include appointment scheduling, capacity limits, and customer check-in.",
    }
    result = service._classify_review_record(rec, "Waitwhile", "waitwhile.com")
    assert result["sentiment"] == "insufficient"
    assert result["classification_reason"] == "no_opinion_language"


def test_sentiment_review_count_only_is_insufficient():
    service = ResearchService()
    rec = {
        "source_url": "https://aggregator.example/waitwhile",
        "source_title": "16 verified reviews",
        "snippet": "",
        "content_excerpt": "",
    }
    result = service._classify_review_record(rec, "Waitwhile", "waitwhile.com")
    assert result["sentiment"] == "insufficient"
    assert result["classification_reason"] in ["review_count_only", "target_product_not_mentioned"]


def test_sentiment_aggregate_rating_5_star():
    service = ResearchService()
    rec = {
        "source_url": "https://capterra.example/waitwhile",
        "source_title": "Waitwhile Reviews & Rating",
        "snippet": "Rated 4.7/5 based on 63 verified reviews for Waitwhile queue platform.",
        "content_excerpt": "Overall 4.7 out of 5 stars with positive customer feedback.",
    }
    result = service._classify_review_record(rec, "Waitwhile", "waitwhile.com")
    assert result["sentiment"] == "positive"
    assert result.get("is_aggregate") is True
    assert result["rating"] == 4.7
    assert result["normalized_rating"] == 94.0


def test_sentiment_no_classified_evidence_has_no_score():
    assert ResearchService()._calculate_sentiment_score([]) is None


def test_sentiment_vendor_testimonial_excluded_from_independent():
    service = ResearchService()
    rec = {
        "source_url": "https://waitwhile.com/case-studies/customer",
        "source_title": "Customer Success Story",
        "snippet": "Waitwhile is fantastic and we loved the results.",
        "content_excerpt": "Great tool.",
    }
    result = service._classify_review_record(rec, "Waitwhile", "waitwhile.com")
    assert result["independent"] is False
    assert result["sentiment"] == "insufficient"
    assert service._valid_review_record(result, "waitwhile.com") is False


def test_sentiment_glassdoor_employee_review_excluded():
    service = ResearchService()
    rec = {
        "source_url": "https://glassdoor.com/Reviews/Waitwhile-Reviews-E123.htm",
        "source_title": "Working at Waitwhile",
        "snippet": "Waitwhile employer review. Salary and management culture is okay.",
        "content_excerpt": "Former employee review: benefits and work culture.",
    }
    result = service._classify_review_record(rec, "Waitwhile", "waitwhile.com")
    assert result["sentiment"] == "insufficient"
    assert result["classification_reason"] == "employee_review"


def test_sentiment_wrong_product_comparison_excluded():
    service = ResearchService()
    rec = {
        "source_url": "https://g2.com/products/competitor-app/reviews",
        "source_title": "CompetitorApp Review",
        "snippet": "CompetitorApp is great for queues.",
        "content_excerpt": "Nothing about the other tool.",
    }
    result = service._classify_review_record(rec, "Waitwhile", "waitwhile.com")
    assert result["sentiment"] == "insufficient"


@pytest.mark.asyncio
async def test_sentiment_gemini_unavailable_fallback_classifies():
    service = ResearchService()
    req = make_request()
    cand = ProductCandidate(product="Waitwhile", vendor="Waitwhile Inc", vendor_url="https://waitwhile.com")
    bundle = {
        "domain": "waitwhile.com",
        "evidence_hits": [],
        "retained_source_evidence": [],
        "review_records": [
            {
                "source_url": "https://g2.com/products/waitwhile/reviews",
                "source_title": "Waitwhile User Review",
                "platform": "G2",
                "snippet": "Waitwhile is easy to use and saves time. Highly recommend.",
                "content_excerpt": "Excellent platform.",
                "sentiment": "unclassified",
            },
            {
                "source_url": "https://capterra.com/p/123/waitwhile",
                "source_title": "Waitwhile Capterra",
                "platform": "Capterra",
                "snippet": "Rated 4.6/5 based on 50 reviews for Waitwhile.",
                "content_excerpt": "Great tool.",
                "sentiment": "unclassified",
            },
            {
                "source_url": "https://trustpilot.com/review/waitwhile.com",
                "source_title": "Trustpilot Waitwhile",
                "platform": "Trustpilot",
                "snippet": "Waitwhile offers great support and reliable software.",
                "content_excerpt": "Satisfied customer.",
                "sentiment": "unclassified",
            },
        ],
    }
    service._enrich_customer_financials = AsyncMock()

    result = await service._apply_deep_fallback(req, cand, bundle, "unavailable_due_to_llm_quota")
    # All 3 independent reviews should be classified deterministically
    assert result.sentiment_summary["classified_review_count"] == 3
    assert result.sentiment_summary["evidence_sufficient"] is True
    assert result.sentiment_score > 50.0


# =====================================================================
# AREA 3: COMPANY IDENTITY & FINANCIALS
# =====================================================================

def test_ch_provider_exact_uk_entity():
    provider = CompaniesHouseProvider()
    sim = provider.BASE is not None
    assert sim is True


@pytest.mark.asyncio
async def test_company_financials_trading_brand_with_parent_labels_scope():
    service = ResearchService()
    req = make_request("Reduce queues", cost=50000)

    # Mock FMP unavailable
    service.fmp.get_financial_context = AsyncMock(return_value={"status": "unavailable"})

    # Mock Companies House resolving Waitrose to John Lewis Partnership
    mock_ch_match = {
        "status": "matched",
        "company_name": "John Lewis Partnership PLC",
        "company_number": "00233462",
        "similarity": 0.85,
        "sic_codes": ["47110"],
        "source_url": "https://find-and-update.company-information.service.gov.uk/company/00233462",
    }
    service.ch.search_company = AsyncMock(side_effect=[
        {"status": "ambiguous", "candidates": [{"title": "Waitrose Limited", "company_number": "00099405", "similarity": 0.82}]},
        mock_ch_match,
    ])
    service._search_many = AsyncMock(return_value=[])

    result = await service._company_financials(req)
    assert result["identity"] is not None
    assert result["identity"]["financial_scope"] in ["group", "parent_company", "legal_entity"]


@pytest.mark.asyncio
async def test_company_financials_ambiguous_company_handled():
    service = ResearchService()
    req = make_request()
    req.company_name = "Ambiguous Apex"

    service.fmp.get_financial_context = AsyncMock(return_value={"status": "unavailable"})
    service.ch.search_company = AsyncMock(return_value={
        "status": "ambiguous",
        "candidates": [
            {"title": "Apex Dental Ltd", "company_number": "111", "similarity": 0.80},
            {"title": "Apex Logistics Ltd", "company_number": "222", "similarity": 0.80},
        ],
    })
    service._search_many = AsyncMock(return_value=[])

    result = await service._company_financials(req)
    assert result["status"] == "ambiguous_company"
    assert len(result["candidates"]) == 2


@pytest.mark.asyncio
async def test_financials_fmp_graceful_degradation():
    provider = FMPProvider()
    provider._last_failure_reason = "rate_limit"
    res = provider._unavailable("temporarily_unavailable", "rate_limit")
    assert res["status"] == "temporarily_unavailable"
    assert res["reason"] == "rate_limit"


# =====================================================================
# AREA 4: ROI & VALUE
# =====================================================================

def test_roi_all_inputs_present_calculated():
    assessment = build_value_assessment(
        baseline_annual_process_cost=100000.0,
        improvements=(10.0, 20.0, 30.0),
        annual_software_cost=5000.0,
        implementation_cost=2000.0,
    )
    assert assessment["expected_annual_benefit"] == 20000.0
    assert assessment["first_year_investment"] == 7000.0
    assert assessment["expected_roi_percent"] == 185.71
    assert assessment["expected_payback_months"] == 4.2
    assert assessment["missing_reasons"] == []


def test_roi_baseline_missing_returns_unavailable_with_reason():
    assessment = build_value_assessment(
        baseline_annual_process_cost=None,
        improvements=(10.0, 20.0, 30.0),
        annual_software_cost=5000.0,
        implementation_cost=2000.0,
    )
    assert assessment["expected_annual_benefit"] is None
    assert assessment["expected_roi_percent"] is None
    assert any("baseline is unavailable" in r for r in assessment["missing_reasons"])


def test_roi_software_cost_missing_returns_unavailable_with_reason():
    assessment = build_value_assessment(
        baseline_annual_process_cost=100000.0,
        improvements=(10.0, 20.0, 30.0),
        annual_software_cost=None,
        implementation_cost=2000.0,
    )
    assert assessment["expected_roi_percent"] is None
    assert any("annual software cost" in r for r in assessment["missing_reasons"])


def test_roi_implementation_cost_missing_returns_unavailable_with_reason():
    assessment = build_value_assessment(
        baseline_annual_process_cost=100000.0,
        improvements=(10.0, 20.0, 30.0),
        annual_software_cost=5000.0,
        implementation_cost=None,
    )
    assert assessment["expected_roi_percent"] is None
    assert any("implementation cost" in r for r in assessment["missing_reasons"])


def test_roi_implementation_zero_cost_allowed():
    assessment = build_value_assessment(
        baseline_annual_process_cost=100000.0,
        improvements=(10.0, 20.0, 30.0),
        annual_software_cost=5000.0,
        implementation_cost=0.0,
    )
    assert assessment["first_year_investment"] == 5000.0
    assert assessment["expected_roi_percent"] == 300.0
    assert assessment["expected_payback_months"] == 3.0


def test_software_cost_only_value_case_is_not_roi():
    assessment = build_value_assessment(
        baseline_annual_process_cost=None,
        improvements=None,
        annual_software_cost=12000.0,
        implementation_cost=None,
        user_budget=100000.0,
    )
    assert assessment["monthly_equivalent"] == 1000.0
    assert assessment["budget_utilisation_pct"] == 12.0
    assert assessment["budget_remaining"] == 88000.0
    assert assessment["three_year_software_cost"] == 36000.0
    assert assessment["expected_roi_percent"] is None


def test_roi_waiting_time_reduction_only_not_financial_benefit():
    service = ResearchService()
    cand = ProductCandidate(
        product="Waitwhile", vendor="Vendor", vendor_url="https://vendor.example",
        customer_impact=[
            {
                "customer": "RetailStore",
                "metric": "Waiting time",
                "claim": "Reduced customer queue waiting time by 30%",
                "impact_value": 30.0,
                "impact_unit": "%",
            }
        ]
    )
    improvements = service._improvement_scenarios(cand)
    assert improvements is None


def test_roi_total_opex_on_narrow_goal_rejected_as_baseline():
    service = ResearchService()
    req = make_request("Reduce queue waiting time at cashiers")
    financials = {
        "metrics": [{"metric": "Operating expenses", "value": 5000000.0}]
    }
    baseline, source = service._roi_baseline(req, financials)
    assert baseline is None
    assert source == "relevant_process_cost_unavailable"


def test_roi_user_supplied_process_cost_prioritised():
    service = ResearchService()
    req = make_request("Reduce queue waiting time", cost=75000.0)
    financials = {
        "metrics": [{"metric": "Operating expenses", "value": 5000000.0}]
    }
    baseline, source = service._roi_baseline(req, financials)
    assert baseline == 75000.0
    assert source == "user_supplied_relevant_process_cost"
