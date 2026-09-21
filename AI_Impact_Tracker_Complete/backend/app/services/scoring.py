from urllib.parse import urlparse


WEIGHTS = {
    "goal_fit": 0.18,
    "sector_fit": 0.12,
    "evidence_score": 0.18,
    "adoption_score": 0.10,
    "momentum_score": 0.07,
    "budget_score": 0.08,
    "sentiment_score": 0.08,
    "impact_score": 0.12,
    "implementation_score": 0.07,
}


def clamp(
    value: float,
    lo: float = 0.0,
    hi: float = 100.0,
) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0

    return max(
        lo,
        min(
            hi,
            number,
        ),
    )


def _get(
    candidate,
    key: str,
    default=None,
):
    """
    Support both ProductCandidate/Pydantic objects
    and plain dictionaries.
    """

    if isinstance(candidate, dict):
        return candidate.get(
            key,
            default,
        )

    return getattr(
        candidate,
        key,
        default,
    )


# ============================================================
# SENTIMENT AVAILABILITY
# ============================================================

def _sentiment_available(
    candidate,
) -> bool:
    """
    Sentiment contributes to final ranking only when
    there is enough independent review evidence.

    Minimum:
    - 3 classified reviews
    - from at least 2 independent domains

    An internal score of 50 is NOT evidence.
    """

    summary = _get(
        candidate,
        "sentiment_summary",
        {},
    ) or {}

    reviews = _get(
        candidate,
        "reviews",
        [],
    ) or []

    if not isinstance(
        summary,
        dict,
    ):
        return False

    try:
        classified_count = int(
            summary.get(
                "classified_review_count",
                0,
            )
            or 0
        )
    except (
        TypeError,
        ValueError,
    ):
        classified_count = 0

    if classified_count < 3:
        return False

    domains = set()

    for review in reviews:
        if not isinstance(
            review,
            dict,
        ):
            continue

        sentiment = str(
            review.get(
                "sentiment"
            )
            or ""
        ).lower().strip()

        if sentiment not in {
            "positive",
            "neutral",
            "negative",
        }:
            continue

        try:
            confidence = float(
                review.get(
                    "confidence",
                    0,
                )
                or 0
            )
        except (
            TypeError,
            ValueError,
        ):
            confidence = 0.0

        if confidence < 0.45:
            continue

        url = str(
            review.get(
                "source_url"
            )
            or ""
        ).strip()

        if not url:
            continue

        try:
            domain = (
                urlparse(url)
                .netloc
                .lower()
                .replace(
                    "www.",
                    "",
                )
            )
        except Exception:
            domain = ""

        if domain:
            domains.add(
                domain
            )

    if len(domains) < 2:
        return False

    score = summary.get(
        "score"
    )

    return score is not None


# ============================================================
# CUSTOMER IMPACT AVAILABILITY
# ============================================================

def _customer_impact_available(
    candidate,
) -> bool:
    """
    Impact contributes to final ranking only when
    quantified customer impact exists.

    A company merely using the product is adoption evidence,
    NOT proof that the product produced measurable impact.
    """

    impacts = _get(
        candidate,
        "customer_impact",
        [],
    ) or []

    for impact in impacts:
        if not isinstance(
            impact,
            dict,
        ):
            continue

        value = impact.get(
            "impact_value"
        )

        if value is None:
            continue

        try:
            float(value)
        except (
            TypeError,
            ValueError,
        ):
            continue

        source_url = str(
            impact.get(
                "source_url"
            )
            or ""
        ).strip()

        if not source_url:
            continue

        return True

    return False


# ============================================================
# BUDGET AVAILABILITY
# ============================================================

def _budget_available(
    candidate,
) -> bool:
    """
    Budget fit contributes only when first-year investment
    can actually be calculated.

    Both values are required:

    annual software cost
    +
    implementation cost

    Partial pricing evidence must NOT turn an internal
    neutral 50 into a real budget score.
    """

    annual_cost = _get(
        candidate,
        "annual_software_cost",
        None,
    )

    implementation_cost = _get(
        candidate,
        "implementation_cost",
        None,
    )

    if annual_cost is None:
        return False

    if implementation_cost is None:
        return False

    try:
        annual_cost = float(
            annual_cost
        )

        implementation_cost = float(
            implementation_cost
        )

    except (
        TypeError,
        ValueError,
    ):
        return False

    if annual_cost < 0:
        return False

    if implementation_cost < 0:
        return False

    first_year_cost = (
        annual_cost
        + implementation_cost
    )

    return first_year_cost > 0


# ============================================================
# FINAL SCORE
# ============================================================

def overall(
    candidate,
) -> float:
    """
    Deterministic evidence-aware final ranking.

    Missing dimensions are excluded and the remaining
    weights are renormalised.

    Therefore:

    No reliable reviews
        -> sentiment does not count

    No quantified customer impact
        -> impact does not count

    Incomplete pricing
        -> budget does not count

    Missing evidence is never represented as an artificial
    50/100 result in the final recommendation.
    """

    available = {
        "goal_fit": True,
        "sector_fit": True,
        "evidence_score": True,
        "adoption_score": True,
        "momentum_score": True,

        "budget_score": (
            _budget_available(
                candidate
            )
        ),

        "sentiment_score": (
            _sentiment_available(
                candidate
            )
        ),

        "impact_score": (
            _customer_impact_available(
                candidate
            )
        ),

        "implementation_score": True,
    }

    weighted_total = 0.0
    active_weight = 0.0

    for key, weight in (
        WEIGHTS.items()
    ):
        if not available.get(
            key,
            True,
        ):
            continue

        value = _get(
            candidate,
            key,
            None,
        )

        if value is None:
            continue

        weighted_total += (
            clamp(
                value
            )
            * weight
        )

        active_weight += (
            weight
        )

    if active_weight <= 0:
        return 0.0

    return round(
        weighted_total
        / active_weight,
        2,
    )


# ============================================================
# BUDGET FIT
# ============================================================

def budget_fit(
    budget: float,
    first_year_cost: float | None,
) -> float:
    """
    Deterministic affordability score.

    The 50 returned for unavailable cost exists only
    for internal schema compatibility.

    overall() excludes budget completely when verified
    first-year investment is unavailable.
    """

    if (
        first_year_cost is None
        or first_year_cost <= 0
    ):
        return 50.0

    try:
        budget = float(
            budget
        )

        first_year_cost = float(
            first_year_cost
        )

    except (
        TypeError,
        ValueError,
    ):
        return 50.0

    if first_year_cost <= 0:
        return 50.0

    ratio = (
        budget
        / first_year_cost
    )

    if ratio >= 1.5:
        return 100.0

    if ratio >= 1.0:
        return 85.0

    if ratio >= 0.8:
        return 55.0

    if ratio >= 0.5:
        return 25.0

    return 5.0