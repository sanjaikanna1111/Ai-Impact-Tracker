from app.services.research import ResearchService
from app.services.value_model import impact_percent, payback_months, roi


def test_adoption_scale_is_not_a_business_outcome():
    assert ResearchService._impact_scope({"claim": "Deployed across 20 stores"}) == "adoption_scale"
    assert ResearchService._impact_scope({"claim": "Served 440,000 customers"}) == "adoption_scale"


def test_wait_time_and_labour_savings_are_classified_as_outcomes():
    assert ResearchService._impact_scope({"claim": "Waiting time reduced by 30%"}) == "waiting_time"
    assert ResearchService._impact_scope({"claim": "Reduced labour cost by 15%"}) == "labour_cost"


def test_blank_or_zero_operational_measurement_never_calculates_percent():
    assert impact_percent(None, 10, "lower") is None
    assert impact_percent(0, 10, "lower") is None
    assert impact_percent(100, 70, "lower") == 30.0
    assert impact_percent(100, 130, "higher") == 30.0


def test_realised_roi_and_payback_require_explicit_positive_inputs():
    assert roi(None, 100) is None
    assert roi(100, None) is None
    assert payback_months(0, 100) is None
    assert payback_months(1200, 600) == 6.0
