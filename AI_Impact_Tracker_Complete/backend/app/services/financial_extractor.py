"""Financial Metrics Intelligence & Extraction Engine.

Provides deterministic candidate detection, controlled financial vocabulary mapping,
currency/unit/period normalisation, false-positive filtering, bounded extraction,
validation, deduplication, and structured provenance preservation.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# =====================================================================
# 1. CONTROLLED FINANCIAL VOCABULARY & CANONICAL MAPPING
# =====================================================================

CANONICAL_METRIC_SPECS: dict[str, dict[str, Any]] = {
    "revenue": {
        "canonical": "revenue",
        "primary_label": "Revenue",
        "aliases": [
            "group revenue",
            "total revenue",
            "revenue",
            "group turnover",
            "turnover",
            "net sales",
            "net revenue",
            "sales",
            "external revenue",
        ],
    },
    "operating_income": {
        "canonical": "operating_income",
        "primary_label": "Operating income",
        "aliases": [
            "adjusted operating profit",
            "adjusted operating income",
            "operating profit",
            "operating income",
            "profit from operations",
            "operating result",
            "statutory operating profit",
        ],
    },
    "operating_expenses": {
        "canonical": "operating_expenses",
        "primary_label": "Operating expenses",
        "aliases": [
            "total operating costs",
            "total operating expenses",
            "operating expenses",
            "operating costs",
            "administrative expenses",
            "distribution expenses",
            "distribution costs",
            "selling, general and administrative expenses",
            "sg&a",
        ],
    },
    "staff_cost": {
        "canonical": "staff_cost",
        "primary_label": "Staff costs",
        "aliases": [
            "staff costs",
            "employee costs",
            "employee expenses",
            "personnel expenses",
            "employment costs",
            "payroll costs",
            "wages and salaries",
            "wages, salaries and social security costs",
        ],
    },
    "cost_of_sales": {
        "canonical": "cost_of_sales",
        "primary_label": "Cost of sales",
        "aliases": [
            "cost of sales",
            "cost of goods sold",
            "cogs",
        ],
    },
    "employee_count": {
        "canonical": "employee_count",
        "primary_label": "Employees",
        "aliases": [
            "employee count",
            "average employees",
            "number of employees",
            "employees",
            "headcount",
        ],
    },
}

# Inverted mapping: lowercase alias -> (canonical_key, primary_label)
_ALIAS_TO_CANONICAL: dict[str, tuple[str, str]] = {}
for _c_key, _spec in CANONICAL_METRIC_SPECS.items():
    for _alias in _spec["aliases"]:
        _ALIAS_TO_CANONICAL[_alias] = (_c_key, _spec["primary_label"])

# =====================================================================
# 2. FALSE POSITIVE / PROHIBITED PHRASES
# =====================================================================

FALSE_POSITIVE_PATTERNS = [
    re.compile(r"\b(?:analysts?|consensus)\s+(?:expect|forecast|predict|estimate|targets?)\b", re.I),
    re.compile(r"\b(?:expected|forecast|projected)\s+(?:to\s+(?:reach|generate|be)|revenue|operating)\b", re.I),
    re.compile(r"\bcompetitor(?:\'s)?\s+(?:revenue|sales|profit|turnover)\b", re.I),
    re.compile(r"\bmarket\s+size\b", re.I),
    re.compile(r"\b(?:customers?|clients?|users?)\s+(?:saved|savings)\b", re.I),
    re.compile(r"\b(?:could|might|potential(?:ly)?|target(?:ed)?)\s+(?:save|reduce|cut)\b", re.I),
    re.compile(r"\bsavings?\s+of\s+(?:£|\$|€)?\d+", re.I),
    re.compile(r"\b(?:per\s+share|share\s+price|dividend|eps|target\s+price|p/e\s+ratio)\b", re.I),
]


def is_false_positive_snippet(snippet: str) -> bool:
    """Return True if the text represents speculative, analyst, competitor, or customer-saving claims."""
    s = snippet.lower()
    return any(p.search(s) for p in FALSE_POSITIVE_PATTERNS)


# =====================================================================
# 3. VALUE & CURRENCY NORMALISATION
# =====================================================================

CURRENCY_MAP = {
    "£": "GBP",
    "gbp": "GBP",
    "pounds": "GBP",
    "sterling": "GBP",
    "$": "USD",
    "usd": "USD",
    "dollars": "USD",
    "€": "EUR",
    "eur": "EUR",
    "euros": "EUR",
}

MULTIPLIER_MAP = {
    "k": 1e3,
    "thousand": 1e3,
    "m": 1e6,
    "mn": 1e6,
    "million": 1e6,
    "millions": 1e6,
    "bn": 1e9,
    "b": 1e9,
    "billion": 1e9,
    "billions": 1e9,
    "tn": 1e12,
    "trillion": 1e12,
}


def parse_reporting_period(
    text: str,
    title: str = "",
    url: str = "",
) -> tuple[str | None, str | None]:
    """Extract (reporting_period, period_end_date) from surrounding text, title, or URL.

    Examples:
        'Year ended 31 August 2025' -> ('FY2025', '2025-08-31')
        '52 weeks ended 14 September 2024' -> ('FY2024', '2024-09-14')
        'FY2024' -> ('FY2024', None)
    """
    month_map = {
        "january": "01", "february": "02", "march": "03", "april": "04",
        "may": "05", "june": "06", "july": "07", "august": "08",
        "september": "09", "october": "10", "november": "11", "december": "12",
        "jan": "01", "feb": "02", "mar": "03", "apr": "04", "jun": "06",
        "jul": "07", "aug": "08", "sep": "09", "sept": "09", "oct": "10",
        "nov": "11", "dec": "12",
    }

    combined = f"{text} {title} {url}"

    # 1. Full ended date
    m_date = re.search(
        r"(?:year|period|52\s+weeks|53\s+weeks)\s+ended\s+(\d{1,2})\s+([A-Za-z]+)\s+(20\d{2})",
        combined,
        re.I,
    )
    if m_date:
        day = m_date.group(1).zfill(2)
        month_name = m_date.group(2).lower()
        year = m_date.group(3)
        month_num = month_map.get(month_name, "12")
        return f"FY{year}", f"{year}-{month_num}-{day}"

    # 2. FY20XX or FYXX
    m_fy = re.search(r"\bFY\s*(20\d{2}|\d{2})\b", combined, re.I)
    if m_fy:
        raw_yr = m_fy.group(1)
        full_yr = f"20{raw_yr}" if len(raw_yr) == 2 else raw_yr
        return f"FY{full_yr}", None

    # 3. YYYY financial year or annual report
    m_yr = re.search(r"\b(20\d{2})\s+(?:financial\s+year|annual\s+report|annual\s+accounts)\b", combined, re.I)
    if m_yr:
        return f"FY{m_yr.group(1)}", None

    # 4. Annual report and accounts YYYY / Results YYYY
    m_yr_after = re.search(r"\b(?:annual\s+report|annual\s+accounts|financial\s+year|results)(?:\s+and\s+accounts)?\s+(20\d{2})\b", combined, re.I)
    if m_yr_after:
        return f"FY{m_yr_after.group(1)}", None

    # 5. Year embedded in document URL or title when accompanied by report/accounts/financial
    meta = f"{title} {url}".lower()
    if any(w in meta for w in ("report", "accounts", "results", "financial", "filing", "profile")):
        m_u = re.search(r"(202[0-9])", meta)
        if m_u:
            return f"FY{m_u.group(1)}", None

    return None, None


def normalize_financial_value(
    value_text: str,
    context: str = "",
    default_currency: str = "GBP",
) -> tuple[float | None, str | None, bool]:
    """Parse monetary string into (normalized_numeric_value, currency, is_negative).

    Handles:
        '£1.2bn' -> (1200000000.0, 'GBP', False)
        '£850m' -> (850000000.0, 'GBP', False)
        '£500 million' -> (500000000.0, 'GBP', False)
        '$(250) million' -> (-250000000.0, 'USD', True)
        '1,420m' -> (1420000000.0, default_currency, False)
    """
    if not value_text:
        return None, None, False

    full_sample = f"{value_text} {context}"

    # Reject per-share or stock price patterns
    if re.search(r"\b(?:per\s+share|share\s+price|dividend|eps)\b", full_sample, re.I):
        return None, None, False

    # Currency detection
    detected_currency = None
    for sym, curr in CURRENCY_MAP.items():
        if sym in value_text.lower() or re.search(rf"\b{re.escape(sym)}\b", full_sample, re.I):
            detected_currency = curr
            break
    if not detected_currency:
        detected_currency = default_currency

    # Negative check: parens or leading minus
    is_neg = bool(re.search(r"\([^)]*\d+[^)]*\)", value_text) or re.search(r"-\s*(?:£|\$|€)?\s*\d", value_text))

    # Clean digits and multiplier
    clean_val = re.sub(r"[()£\$€\s,]", "", value_text).replace("-", "")
    m = re.search(r"^(\d+(?:\.\d+)?)\s*([a-zA-Z]+)?$", clean_val)
    if not m:
        # Fallback regex in context
        m = re.search(r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(k|m|mn|million|bn|b|billion|tn|trillion)?\b", value_text, re.I)
        if not m:
            return None, detected_currency, is_neg
        num_str = m.group(1).replace(",", "")
        mult_str = (m.group(2) or "").lower()
    else:
        num_str = m.group(1)
        mult_str = (m.group(2) or "").lower()

    # If multiplier not found on value_text, check immediate context
    if not mult_str:
        m_ctx = re.search(r"\b(k|thousand|m|mn|million|millions|bn|b|billion|billions|tn|trillion)\b", context[:40], re.I)
        if m_ctx:
            mult_str = m_ctx.group(1).lower()

    try:
        raw_num = float(num_str)
    except ValueError:
        return None, detected_currency, is_neg

    mult = MULTIPLIER_MAP.get(mult_str, 1.0)
    final_val = raw_num * mult
    if is_neg:
        final_val = -final_val

    return final_val, detected_currency, is_neg


# =====================================================================
# 4. DETERMINISTIC EXTRACTION PATTERNS
# =====================================================================

_VERB_FILLER = r"(?:\s+(?:was|were|reached|totaled|totalled|increased(?:\s+to)?|decreased(?:\s+to)?|of|stood\s+at|came\s+in\s+at|reported\s+as|is))?"
_VALUE_PATTERN = r"(?:£|\$|€|GBP|USD|EUR)?\s*\(?-?\s*(?:£|\$|€)?\s*\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*\)?\s*(?:k|thousand|m|mn|million|millions|bn|b|billion|billions|tn|trillion)?"


def find_candidate_excerpts(
    content: str,
    keywords: list[str] | None = None,
    max_excerpts: int = 12,
    window_chars: int = 250,
) -> list[str]:
    """Scan document content for keywords and return compact surrounding excerpts."""
    if not content:
        return []

    target_keywords = keywords or list(_ALIAS_TO_CANONICAL.keys())
    sorted_keywords = sorted(target_keywords, key=len, reverse=True)
    pattern = re.compile(rf"\b({'|'.join(re.escape(k) for k in sorted_keywords[:20])})\b", re.I)

    excerpts: list[str] = []
    seen_spans: set[int] = set()

    for match in pattern.finditer(content):
        start = max(0, match.start() - 80)
        end = min(len(content), match.end() + window_chars)
        span_bucket = start // 100
        if span_bucket in seen_spans:
            continue
        seen_spans.add(span_bucket)

        excerpt = content[start:end].replace("\r", " ")
        excerpt = re.sub(r"[ \t]+", " ", excerpt).strip()
        if not is_false_positive_snippet(excerpt):
            excerpts.append(excerpt)
        if len(excerpts) >= max_excerpts:
            break

    return excerpts


def extract_deterministic_metrics(
    text: str,
    source_url: str = "",
    source_title: str = "",
    financial_scope: str = "legal_entity",
    company_name: str = "",
    default_currency: str = "GBP",
) -> list[dict[str, Any]]:
    """Deterministically extract verified metrics from plain text/markdown content.

    Returns structured metric dictionaries strictly matching the system's
    provenance and validation rules.
    """
    results: list[dict[str, Any]] = []
    if not text:
        return results

    # Global document reporting period check
    doc_period, doc_date = parse_reporting_period(text[:2000], title=source_title, url=source_url)

    # Scan for each canonical alias
    for alias, (canonical_key, primary_label) in _ALIAS_TO_CANONICAL.items():
        pattern = re.compile(
            rf"\b({re.escape(alias)})\b\s*(?::|=|\-)?{_VERB_FILLER}\s*({_VALUE_PATTERN})",
            re.I,
        )

        for match in pattern.finditer(text):
            reported_label = match.group(1).strip()
            raw_val_str = match.group(2).strip()

            # Surrounding window (50 chars before, 100 chars after)
            w_start = max(0, match.start() - 50)
            w_end = min(len(text), match.end() + 100)
            window = text[w_start:w_end]

            if is_false_positive_snippet(window):
                continue

            val, curr, is_neg = normalize_financial_value(
                raw_val_str,
                context=window,
                default_currency=default_currency,
            )
            if val is None or val == 0:
                continue

            # Plausibility threshold: aggregates for enterprise/mid-market should not be trivial per-share prices
            if canonical_key in {"revenue", "operating_income", "operating_expenses", "staff_cost"}:
                if abs(val) < 10000:
                    continue

            # Check for local period override in window
            local_period, local_date = parse_reporting_period(window, title=source_title, url=source_url)
            reporting_period = local_period or doc_period
            period_end = local_date or doc_date

            is_adjusted = "adjusted" in reported_label.lower()

            results.append({
                "canonical_metric": canonical_key,
                "reported_label": reported_label,
                "metric": primary_label,
                "value": val,
                # Counts are never money.  Do not propagate a document's
                # reporting currency onto headcount simply because it is numeric.
                "currency": None if canonical_key == "employee_count" else (curr or default_currency),
                "unit": "employees" if canonical_key == "employee_count" else "absolute",
                "reporting_period": reporting_period,
                "period_end": period_end,
                "fiscal_year": reporting_period.replace("FY", "") if reporting_period and "FY" in reporting_period else None,
                "financial_scope": financial_scope,
                "company_name": company_name,
                "is_adjusted": is_adjusted,
                "is_derived": False,
                "source": "Official document / filing",
                "source_title": source_title or "Annual report / financial filing",
                "source_url": source_url,
                "source_type": "annual_report" if "report" in (source_title + source_url).lower() else "financial_statement",
                "confidence": 0.92 if ("annual" in (source_title + source_url).lower() or "accounts" in (source_title + source_url).lower()) else 0.85,
                "verified": True,
            })

    return results


# =====================================================================
# 5. DEDUPLICATION & SOURCE PRIORITISATION
# =====================================================================

SOURCE_PRIORITY = {
    "annual_report": 1,
    "regulatory_filing": 2,
    "companies_house": 3,
    "sec_edgar": 3,
    "financial_statement": 4,
    "fmp": 5,
    "structured_provider": 5,
    "secondary_source": 6,
    "web_evidence": 7,
}


def deduplicate_and_prioritise_metrics(
    metrics: list[dict[str, Any]],
    identity: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Deduplicate metrics by canonical metric and financial scope.

    Prefers recent reporting periods (latest fiscal year) and highest source priority.
    Enforces:
    - Meaningful reporting period (metrics without period are excluded from verified).
    - Scope verification (parent_company scope requires verified parent relationship).
    - Temporal consistency (stale metrics older than latest_year - 1 are excluded from current summary).
    - Highest source priority and recency.
    """
    if not metrics:
        return []

    # Clean out obvious share prices or tiny values
    has_parent = False
    if identity:
        has_parent = bool(
            identity.get("parent_company")
            or identity.get("financial_scope") == "parent_company"
            or identity.get("group_name")
        )

    # Clean out obvious share prices, tiny values, or metrics without reporting period
    filtered: list[dict[str, Any]] = []
    for m in metrics:
        canon = m.get("canonical_metric")
        val = m.get("value")
        if val is None or val == 0:
            continue
        if canon in {"revenue", "operating_income", "operating_expenses", "staff_cost"} and abs(float(val)) < 10000:
            continue

        # Requirement 4 & 5: A verified metric must have a meaningful reporting period
        period = str(m.get("reporting_period") or "").strip()
        if not period or period.lower() in {"none", "null", "unavailable", "unknown"}:
            m["verified"] = False
            m["incomplete_reason"] = "missing_reporting_period"
            logger.info("[FINANCIALS] Excluded metric without reporting period: %s (%s)", canon, val)
            continue

        # Parent scope verification
        if m.get("financial_scope") == "parent_company" and not has_parent and identity is not None:
            # If entity has no parent, do not treat as verified parent metric
            logger.warning("[FINANCIALS] Parent scope metric rejected because entity has no verified parent: %s", canon)
            continue

        filtered.append(m)

    if not filtered:
        return []

    # Extract year for each metric to determine latest defensible reporting year
    def _extract_year(item: dict[str, Any]) -> int | None:
        for f in ("reporting_period", "period_end", "fiscal_year"):
            val = str(item.get(f) or "")
            m_yr = re.search(r"(?:19|20)(\d{2})", val)
            if m_yr:
                return int(m_yr.group(0))
        return None

    years = [_extract_year(m) for m in filtered]
    valid_years = [y for y in years if y is not None]
    latest_year = max(valid_years) if valid_years else None

    # Temporal consistency: exclude stale metrics (more than 1 year older than latest_year, e.g. 2009 vs 2025)
    temporally_consistent: list[dict[str, Any]] = []
    for m in filtered:
        yr = _extract_year(m)
        if yr is not None and latest_year is not None and yr < latest_year - 1:
            m["verified"] = False
            m["is_historical"] = True
            m["incomplete_reason"] = f"stale_reporting_period_{yr}_vs_latest_{latest_year}"
            logger.info(
                "[FINANCIALS] Excluded stale metric: %s=%s (%s) vs latest %s",
                m.get("canonical_metric"),
                m.get("value"),
                m.get("reporting_period"),
                latest_year,
            )
            continue
        temporally_consistent.append(m)

    # Group by (canonical_metric, financial_scope)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for m in temporally_consistent:
        canon = m.get("canonical_metric") or m.get("metric", "").lower().replace(" ", "_")
        scope = m.get("financial_scope", "legal_entity")
        key = (canon, scope)
        grouped.setdefault(key, []).append(m)

    retained: list[dict[str, Any]] = []

    for key, group in grouped.items():
        def _score(item: dict[str, Any]) -> tuple[int, int, int, float]:
            st = str(item.get("source_type", "")).lower()
            pri = SOURCE_PRIORITY.get(st, 8)
            conf = float(item.get("confidence", 0.7))
            yr = _extract_year(item) or 0
            is_latest = 1 if (latest_year and yr == latest_year) else 0
            return (is_latest, yr, -pri, conf)

        group.sort(key=_score, reverse=True)
        retained.append(group[0])

    metric_order = {
        "revenue": 1,
        "operating_income": 2,
        "operating_expenses": 3,
        "staff_cost": 4,
        "cost_of_sales": 5,
        "employee_count": 6,
    }

    retained.sort(
        key=lambda x: metric_order.get(x.get("canonical_metric", ""), 99)
    )

    return retained
