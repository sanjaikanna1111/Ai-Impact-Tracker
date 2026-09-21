from typing import Any


# ============================================================
# BASIC FINANCIAL CALCULATIONS
# ============================================================

def roi(
    annual_benefit: float | None,
    investment: float | None,
) -> float | None:
    """
    ROI (%) =
    (annual benefit - investment)
    / investment * 100
    """

    if annual_benefit is None:
        return None

    if investment is None:
        return None

    if investment <= 0:
        return None

    return round(
        (
            (
                float(annual_benefit)
                - float(investment)
            )
            / float(investment)
        )
        * 100.0,
        2,
    )


def payback_months(
    annual_benefit: float | None,
    investment: float | None,
) -> float | None:
    """
    Payback period in months =
    investment / monthly benefit
    """

    if annual_benefit is None:
        return None

    if investment is None:
        return None

    if annual_benefit <= 0:
        return None

    if investment <= 0:
        return None

    monthly_benefit = (
        float(annual_benefit)
        / 12.0
    )

    if monthly_benefit <= 0:
        return None

    return round(
        float(investment)
        / monthly_benefit,
        2,
    )


def impact_percent(
    baseline: float | None,
    actual: float | None,
    direction: str,
) -> float | None:
    """
    Calculate realised KPI improvement.

    direction="lower":
        Lower actual value is better.

    direction="higher":
        Higher actual value is better.
    """

    if baseline is None or actual is None:
        return None

    baseline = float(baseline)
    actual = float(actual)

    if baseline <= 0:
        return None

    if direction == "lower":
        value = (
            (
                baseline
                - actual
            )
            / baseline
        ) * 100.0

    else:
        value = (
            (
                actual
                - baseline
            )
            / baseline
        ) * 100.0

    return round(
        value,
        2,
    )


# ============================================================
# PRE-IMPLEMENTATION VALUE ASSESSMENT
# ============================================================

def build_value_assessment(
    baseline_annual_process_cost: float | None,
    improvements: tuple[
        float,
        float,
        float,
    ] | None,
    annual_software_cost: float | None,
    implementation_cost: float | None,
    user_budget: float | None = None,
    basis: str = "",
) -> dict[str, Any]:
    """
    Build an evidence-based pre-implementation
    business value case.

    Financial logic:

    annual benefit =
        relevant annual process cost
        * improvement %

    first-year investment =
        annual software cost
        + implementation cost

    ROI =
        (annual benefit - first-year investment)
        / first-year investment
        * 100

    Payback =
        first-year investment
        / monthly annual benefit

    Missing evidence remains None.
    """

    result: dict[str, Any] = {
        "baseline_annual_process_cost": (
            baseline_annual_process_cost
        ),

        "conservative_improvement_percent": None,
        "expected_improvement_percent": None,
        "optimistic_improvement_percent": None,

        "conservative_annual_benefit": None,
        "expected_annual_benefit": None,
        "optimistic_annual_benefit": None,

        "annual_software_cost": (
            annual_software_cost
        ),
        "monthly_equivalent": None,
        "budget_utilisation_pct": None,
        "budget_remaining": None,
        "three_year_software_cost": None,

        "implementation_cost": (
            implementation_cost
        ),

        "first_year_investment": None,

        "conservative_roi_percent": None,
        "expected_roi_percent": None,
        "optimistic_roi_percent": None,

        "conservative_payback_months": None,
        "expected_payback_months": None,
        "optimistic_payback_months": None,

        "confidence": "insufficient",
        "basis": basis,
        "missing_reasons": [],
    }

    # Track itemized missing reasons for clear decision intelligence
    missing_reasons = []
    if improvements is None:
        missing_reasons.append("No directly quantified customer financial impact percentage was available.")
    if baseline_annual_process_cost is None or baseline_annual_process_cost <= 0:
        missing_reasons.append("Relevant annual process cost baseline is unavailable.")
    if annual_software_cost is None:
        missing_reasons.append("Verified annual software cost was not publicly available.")
    if implementation_cost is None:
        missing_reasons.append("Verified implementation cost was not publicly available.")
    result["missing_reasons"] = missing_reasons

    # A verified fixed annual subscription is still useful decision evidence
    # when ROI inputs are incomplete. These are cost metrics, never ROI.
    if annual_software_cost is not None:
        try:
            fixed_annual_cost = float(annual_software_cost)
        except (TypeError, ValueError):
            fixed_annual_cost = -1
        if fixed_annual_cost >= 0:
            result["monthly_equivalent"] = round(fixed_annual_cost / 12.0, 2)
            result["three_year_software_cost"] = round(fixed_annual_cost * 3.0, 2)
            if user_budget is not None and float(user_budget) >= 0:
                result["budget_utilisation_pct"] = round(fixed_annual_cost / float(user_budget) * 100.0, 2) if float(user_budget) else None
                result["budget_remaining"] = round(float(user_budget) - fixed_annual_cost, 2)

    # --------------------------------------------------------
    # IMPROVEMENT EVIDENCE REQUIRED
    # --------------------------------------------------------

    if improvements is None:
        return result

    (
        conservative,
        expected,
        optimistic,
    ) = improvements

    conservative = max(
        float(conservative),
        0.0,
    )

    expected = max(
        float(expected),
        0.0,
    )

    optimistic = max(
        float(optimistic),
        0.0,
    )

    result[
        "conservative_improvement_percent"
    ] = round(
        conservative,
        2,
    )

    result[
        "expected_improvement_percent"
    ] = round(
        expected,
        2,
    )

    result[
        "optimistic_improvement_percent"
    ] = round(
        optimistic,
        2,
    )

    # --------------------------------------------------------
    # RELEVANT PROCESS COST REQUIRED FOR SAVINGS
    # --------------------------------------------------------

    if (
        baseline_annual_process_cost is None
        or baseline_annual_process_cost <= 0
    ):
        result["confidence"] = "partial"

        return result

    baseline = float(
        baseline_annual_process_cost
    )

    conservative_benefit = (
        baseline
        * conservative
        / 100.0
    )

    expected_benefit = (
        baseline
        * expected
        / 100.0
    )

    optimistic_benefit = (
        baseline
        * optimistic
        / 100.0
    )

    result[
        "conservative_annual_benefit"
    ] = round(
        conservative_benefit,
        2,
    )

    result[
        "expected_annual_benefit"
    ] = round(
        expected_benefit,
        2,
    )

    result[
        "optimistic_annual_benefit"
    ] = round(
        optimistic_benefit,
        2,
    )

    # --------------------------------------------------------
    # COMPLETE INVESTMENT REQUIRED FOR ROI
    #
    # IMPORTANT:
    # Unknown implementation cost MUST NOT become £0.
    # --------------------------------------------------------

    if annual_software_cost is None:
        result["confidence"] = "partial"

        return result

    if implementation_cost is None:
        result["confidence"] = "partial"

        return result

    annual_software_cost = float(
        annual_software_cost
    )

    implementation_cost = float(
        implementation_cost
    )

    if annual_software_cost < 0:
        return result

    if implementation_cost < 0:
        return result

    first_year_investment = (
        annual_software_cost
        + implementation_cost
    )

    if first_year_investment <= 0:
        return result

    result[
        "first_year_investment"
    ] = round(
        first_year_investment,
        2,
    )

    # --------------------------------------------------------
    # CONSERVATIVE ROI + PAYBACK
    # --------------------------------------------------------

    result[
        "conservative_roi_percent"
    ] = roi(
        conservative_benefit,
        first_year_investment,
    )

    result[
        "conservative_payback_months"
    ] = payback_months(
        conservative_benefit,
        first_year_investment,
    )

    # --------------------------------------------------------
    # EXPECTED ROI + PAYBACK
    # --------------------------------------------------------

    result[
        "expected_roi_percent"
    ] = roi(
        expected_benefit,
        first_year_investment,
    )

    result[
        "expected_payback_months"
    ] = payback_months(
        expected_benefit,
        first_year_investment,
    )

    # --------------------------------------------------------
    # OPTIMISTIC ROI + PAYBACK
    # --------------------------------------------------------

    result[
        "optimistic_roi_percent"
    ] = roi(
        optimistic_benefit,
        first_year_investment,
    )

    result[
        "optimistic_payback_months"
    ] = payback_months(
        optimistic_benefit,
        first_year_investment,
    )

    result["confidence"] = (
        "evidence_based"
    )

    return result
