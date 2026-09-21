import httpx
import pytest
from unittest.mock import AsyncMock

from app.config import settings
from app.providers.fmp import FMPProvider
from app.schemas import ResearchRequest
from app.services.research import ResearchService


@pytest.fixture(autouse=True)
def fmp_settings(monkeypatch):
    monkeypatch.setattr(settings, "fmp_api_key", "test-key")
    monkeypatch.setattr(settings, "fmp_base_url", "https://fmp.test/stable")


def client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_missing_api_key_reports_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "fmp_api_key", "")
    result = await FMPProvider().get_financial_context("Tesco PLC", "UK")
    assert result["status"] == "not_configured"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500])
async def test_service_failures_are_optional_enrichment(status):
    provider = FMPProvider(client(lambda request: httpx.Response(status)))
    result = await provider.get_financial_context("Tesco PLC")
    assert result["status"] == "temporarily_unavailable"


@pytest.mark.asyncio
async def test_network_failure_is_contained():
    def fail(request):
        raise httpx.ConnectError("DNS failure", request=request)
    result = await FMPProvider(client(fail)).get_financial_context("Tesco PLC")
    assert result["status"] == "temporarily_unavailable"


@pytest.mark.asyncio
async def test_company_not_found():
    provider = FMPProvider(client(lambda request: httpx.Response(200, json=[])))
    assert (await provider.search_company("D-Mart"))["status"] == "not_found"


@pytest.mark.asyncio
async def test_ambiguous_company_is_not_selected():
    def handler(request):
        return httpx.Response(200, json=[
            {"symbol": "ONE", "name": "Example Holdings", "exchange": "LSE"},
            {"symbol": "TWO", "name": "Example Holding", "exchange": "LSE"},
        ])
    result = await FMPProvider(client(handler)).search_company("Example Holding")
    assert result["status"] == "ambiguous"


@pytest.mark.asyncio
async def test_operating_expenses_uses_explicit_fmp_field():
    def handler(request):
        return httpx.Response(200, json=[{
            "operatingExpenses": 1250000,
            "reportedCurrency": "GBP",
            "calendarYear": "2025",
        }])
    result = await FMPProvider(client(handler)).get_operating_expenses("EXM")
    assert result["value"] == 1250000
    assert result["raw_field"] == "operatingExpenses"
    assert result["currency"] == "GBP"


@pytest.mark.asyncio
async def test_missing_operating_expenses_is_not_derived():
    provider = FMPProvider(client(lambda request: httpx.Response(200, json=[{
        "revenue": 100, "costOfRevenue": 50, "reportedCurrency": "GBP"
    }])))
    assert await provider.get_operating_expenses("EXM") is None


@pytest.mark.asyncio
async def test_valid_listed_company_context_has_provenance():
    def handler(request):
        if request.url.path.endswith("search-symbol"):
            return httpx.Response(200, json=[{"symbol": "EXM", "name": "Example PLC", "exchange": "LSE"}])
        if request.url.path.endswith("profile"):
            return httpx.Response(200, json=[{"companyName": "Example PLC", "country": "UK", "industry": "Retail"}])
        return httpx.Response(200, json=[{"operatingExpenses": 1000, "revenue": 2000, "reportedCurrency": "GBP", "calendarYear": "2025"}])
    result = await FMPProvider(client(handler)).get_financial_context("Example PLC", "UK")
    assert result["status"] == "available"
    assert result["metrics"][0]["provider"] == "FMP"
    assert result["metrics"][0]["raw_field"] == "operatingExpenses"


@pytest.mark.asyncio
async def test_financial_context_is_cached_per_company():
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=[])
    provider = FMPProvider(client(handler))
    await provider.get_financial_context("Unknown Co")
    await provider.get_financial_context("Unknown Co")
    assert calls == 1


def test_process_impact_scope_is_not_total_opex():
    assert ResearchService._impact_scope({"claim": "Checkout labour costs reduced by 15%"}) == "labour_cost"


def test_explicit_company_wide_opex_scope_is_recognised():
    assert ResearchService._impact_scope({"claim": "Total operating expenses reduced by 7%"}) == "total_operating_expenses"


@pytest.mark.asyncio
async def test_user_company_fmp_context_is_exposed_without_roi_baseline():
    service = ResearchService()
    service.fmp.get_financial_context = AsyncMock(return_value={
        "status": "available", "symbol": "EXM", "company_name": "Example PLC",
        "identity": {"match_confidence": 0.99}, "metrics": [],
        "operating_expenses": 1000, "currency": "GBP", "fiscal_year": 2025,
    })
    req = request("Reduce checkout waiting time")
    req.company_name = "Example PLC"
    context = await service._company_financials(req)
    assert context["fmp"]["operating_expenses"] == 1000
    assert service._roi_baseline(request("Reduce checkout waiting time"), context)[0] is None


@pytest.mark.asyncio
async def test_customer_financial_failure_does_not_remove_evidence():
    service = ResearchService()
    service.fmp.get_financial_context = AsyncMock(return_value={"status": "not_found"})
    candidate = type("Candidate", (), {"customers": [{"customer": "Unknown Co", "source_url": "https://example.com"}], "customer_impact": []})()
    await service._enrich_customer_financials(candidate)
    assert candidate.customers[0]["source_url"] == "https://example.com"
    assert candidate.customers[0]["financial_context"]["status"] == "unavailable"


def request(goal: str, process_cost: float | None = None) -> ResearchRequest:
    return ResearchRequest(sector="Retail", business_goal=goal, budget=10000, company_size="Large", employees=1000, current_annual_process_cost=process_cost)


def test_process_cost_overrides_total_opex():
    service = ResearchService()
    baseline, source = service._roi_baseline(request("Reduce company-wide operating expenses", 200), {"metrics": [{"metric": "Operating expenses", "value": 1000}]})
    assert (baseline, source) == (200.0, "user_supplied_relevant_process_cost")


def test_total_opex_is_blocked_for_process_specific_goal():
    service = ResearchService()
    baseline, source = service._roi_baseline(request("Reduce checkout waiting time"), {"metrics": [{"metric": "Operating expenses", "value": 1000}]})
    assert baseline is None
    assert source == "relevant_process_cost_unavailable"


def test_total_opex_allowed_for_explicit_broad_goal():
    service = ResearchService()
    baseline, source = service._roi_baseline(request("Reduce total operating expenses across the company"), {"metrics": [{"metric": "Operating expenses", "value": 1000}]})
    assert (baseline, source) == (1000.0, "verified_company_operating_costs")
