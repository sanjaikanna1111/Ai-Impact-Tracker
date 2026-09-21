import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.providers.gemini import GeminiProvider
from app.providers.serper import SerperProvider
from app.schemas import BusinessUnderstanding, ResearchRequest, SearchResult
from app.config import settings
from app.services.financial_extractor import extract_deterministic_metrics
from app.services.research import CompactDeepAnalysis, ResearchService


def test_compact_gemini_schema_removes_rejected_constraints_and_refs():
    schema = GeminiProvider._response_schema(CompactDeepAnalysis)
    rendered = str(schema)
    for forbidden in ("$defs", "$ref", "maxItems", "additionalProperties"):
        assert forbidden not in rendered
    assert "products" in schema["properties"]


def test_serper_query_deduplicates_product_equal_to_vendor():
    assert SerperProvider.normalize_search_query('"Qminder" "Qminder" reviews') == '"Qminder" reviews'
    assert SerperProvider.normalize_search_query('site:vendor.example  "Product"  "Product" customer') == 'site:vendor.example "Product" customer'


def test_serper_query_removes_control_characters_and_caps_length():
    assert "\n" not in SerperProvider.normalize_search_query('Product\nreviews')
    assert len(SerperProvider.normalize_search_query("x" * 700)) == 500


@pytest.mark.asyncio
async def test_gemini_sdk_request_has_hard_timeout(monkeypatch):
    async def never_returns(**_kwargs):
        await asyncio.Event().wait()

    client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=never_returns))
    )
    monkeypatch.setattr(settings, "gemini_timeout_seconds", 1)
    with pytest.raises(TimeoutError):
        await GeminiProvider()._generate_with_client(client, "test", BusinessUnderstanding)


@pytest.mark.asyncio
async def test_business_understanding_uses_input_only_fallback():
    service = ResearchService()
    service.gemini.structured = AsyncMock(side_effect=RuntimeError("503 unavailable"))
    req = ResearchRequest(sector="Retail", business_goal="Reduce checkout waiting time", budget=20000, company_size="Large", employees=100, company_name="Primark", company_country="United Kingdom")
    result = await service._business_understanding(req)
    assert result.business_problem == req.business_goal
    assert result.desired_outcomes == [req.business_goal]
    assert result.search_queries


def test_employee_count_is_a_count_not_currency():
    metrics = extract_deterministic_metrics(
        "Annual report 2025. Average employees were 46,820.",
        source_title="Annual report 2025",
    )
    employee = next(metric for metric in metrics if metric["canonical_metric"] == "employee_count")
    assert employee["value"] == 46820
    assert employee["unit"] == "employees"
    assert employee["currency"] is None


@pytest.mark.asyncio
async def test_discovery_503_uses_serper_fallback():
    service = ResearchService()
    service.gemini.structured = AsyncMock(side_effect=RuntimeError("503 service unavailable"))
    service._search_many = AsyncMock(return_value=[SearchResult(title="Waitwhile", url="https://waitwhile.com", snippet="Official queue-management software")])
    req = ResearchRequest(sector="Retail", business_goal="Reduce queues", budget=1000, company_size="Large", employees=100)
    understanding = type("Understanding", (), {"search_queries": ["queue software"]})()
    seeds, _ = await service._discover_candidates(req, understanding)
    assert seeds
