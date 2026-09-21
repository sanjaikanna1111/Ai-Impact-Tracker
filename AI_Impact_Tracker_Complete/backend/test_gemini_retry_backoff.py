import asyncio

import pytest
from unittest.mock import AsyncMock

from app.providers.gemini import GeminiProvider
from app.schemas import BusinessUnderstanding, ResearchRequest, SearchResult
from app.services.research import ResearchService


class ProviderError(RuntimeError):
    def __init__(self, message: str, headers=None):
        super().__init__(message)
        self.headers = headers or {}


def _provider(key_count=1):
    provider = GeminiProvider()
    provider.clients = [object() for _ in range(key_count)]
    return provider


def _result():
    return BusinessUnderstanding(
        business_problem="queues",
        desired_outcomes=["shorter queues"],
        processes=["checkout"],
        search_queries=["queue software"],
    )


@pytest.mark.asyncio
async def test_gemini_success_has_no_retry():
    provider = _provider()
    provider._generate_with_client = AsyncMock(return_value=_result())

    result = await provider.structured("test", BusinessUnderstanding)

    assert result.business_problem == "queues"
    assert provider._generate_with_client.await_count == 1


@pytest.mark.asyncio
async def test_gemini_503_retries_same_key_with_short_backoff(monkeypatch):
    provider = _provider()
    provider._generate_with_client = AsyncMock(
        side_effect=[ProviderError("503 UNAVAILABLE high demand"), _result()]
    )
    sleeps = []

    async def record_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("app.providers.gemini.asyncio.sleep", record_sleep)
    await provider.structured("test", BusinessUnderstanding)

    assert provider._generate_with_client.await_count == 2
    assert len(sleeps) == 1
    assert 2.0 <= sleeps[0] <= 2.5


@pytest.mark.asyncio
async def test_gemini_timeout_retries_and_then_succeeds(monkeypatch):
    provider = _provider()
    provider._generate_with_client = AsyncMock(
        side_effect=[asyncio.TimeoutError(), _result()]
    )

    async def no_sleep(_delay):
        pass

    monkeypatch.setattr("app.providers.gemini.asyncio.sleep", no_sleep)
    result = await provider.structured("test", BusinessUnderstanding)

    assert result.business_problem == "queues"
    assert provider._generate_with_client.await_count == 2


@pytest.mark.asyncio
async def test_transient_failures_rotate_to_fallback_key(monkeypatch):
    provider = _provider(key_count=2)
    provider._generate_with_client = AsyncMock(
        side_effect=[ProviderError("503 UNAVAILABLE")] * 3 + [_result()]
    )

    async def no_sleep(_delay):
        pass

    monkeypatch.setattr("app.providers.gemini.asyncio.sleep", no_sleep)
    await provider.structured("test", BusinessUnderstanding)

    assert provider._generate_with_client.await_count == 4
    assert provider._preferred_client_index == 1


@pytest.mark.asyncio
async def test_gemini_repeated_503_uses_three_attempts_per_key_then_rotates(monkeypatch):
    provider = _provider(key_count=2)
    provider._generate_with_client = AsyncMock(
        side_effect=[ProviderError("503 UNAVAILABLE")] * 6
    )

    async def no_sleep(_delay):
        pass

    monkeypatch.setattr("app.providers.gemini.asyncio.sleep", no_sleep)
    with pytest.raises(RuntimeError, match="All configured Gemini"):
        await provider.structured("test", BusinessUnderstanding)

    assert provider._generate_with_client.await_count == 6


@pytest.mark.asyncio
async def test_gemini_minute_limit_uses_provider_delay_not_short_backoff(monkeypatch):
    provider = _provider()
    provider._generate_with_client = AsyncMock(
        side_effect=[ProviderError("429 RESOURCE_EXHAUSTED GenerateRequestsPerMinutePerProjectPerModel-FreeTier retryDelay: 38s"), _result()]
    )
    sleeps = []

    async def record_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("app.providers.gemini.asyncio.sleep", record_sleep)
    await provider.structured("test", BusinessUnderstanding)

    assert provider._generate_with_client.await_count == 2
    assert sleeps == [39.0]


@pytest.mark.asyncio
async def test_daily_quota_disables_key_for_the_current_run():
    provider = _provider(key_count=2)
    provider._generate_with_client = AsyncMock(
        side_effect=[
            ProviderError("429 RESOURCE_EXHAUSTED GenerateRequestsPerDayPerProjectPerModel-FreeTier"),
            _result(),
            _result(),
        ]
    )

    await provider.structured("first", BusinessUnderstanding)
    await provider.structured("later", BusinessUnderstanding)

    assert provider._generate_with_client.await_count == 3
    assert provider._key_health == ["DAILY_QUOTA_EXHAUSTED", "AVAILABLE"]


@pytest.mark.asyncio
async def test_all_daily_quota_keys_are_skipped_by_later_stages():
    provider = _provider(key_count=2)
    provider._generate_with_client = AsyncMock(
        side_effect=[
            ProviderError("429 GenerateRequestsPerDayPerProjectPerModel-FreeTier"),
            ProviderError("429 GenerateRequestsPerDayPerProjectPerModel-FreeTier"),
        ]
    )

    with pytest.raises(RuntimeError, match="All configured Gemini"):
        await provider.structured("first", BusinessUnderstanding)
    assert provider._generate_with_client.await_count == 2

    with pytest.raises(RuntimeError, match="No usable Gemini"):
        await provider.structured("later", BusinessUnderstanding)
    assert provider._generate_with_client.await_count == 2


@pytest.mark.asyncio
async def test_discovery_falls_back_when_all_keys_were_already_disabled():
    service = ResearchService()
    req = ResearchRequest(sector="Retail", business_goal="Reduce checkout waiting time", budget=100000, company_size="Large", employees=100)
    understanding = BusinessUnderstanding(business_problem=req.business_goal, desired_outcomes=[], processes=[], search_queries=["retail queue software"])
    service.gemini.clients = [object(), object()]
    service.gemini._key_health = ["DAILY_QUOTA_EXHAUSTED", "DAILY_QUOTA_EXHAUSTED"]
    service.gemini._generate_with_client = AsyncMock()
    result = SearchResult(title="Qminder | Queue Management System", url="https://qminder.com", snippet="Checkout queue software solution")
    service._search_many = AsyncMock(side_effect=[[result], []])
    service._resolve_vendor_url = AsyncMock(side_effect=lambda seed: seed)

    seeds, _ = await service._discover_candidates(req, understanding)

    assert [seed.vendor for seed in seeds] == ["Qminder"]
    assert service.gemini._generate_with_client.await_count == 0


@pytest.mark.asyncio
async def test_discovery_does_not_hide_unrelated_programming_errors():
    service = ResearchService()
    req = ResearchRequest(sector="Retail", business_goal="Reduce checkout waiting time", budget=100000, company_size="Large", employees=100)
    understanding = BusinessUnderstanding(business_problem=req.business_goal, desired_outcomes=[], processes=[], search_queries=["retail queue software"])
    service.gemini.structured = AsyncMock(side_effect=RuntimeError("unexpected logic bug"))
    service._search_many = AsyncMock(return_value=[SearchResult(title="Qminder | Queue Management System", url="https://qminder.com", snippet="Checkout queue software solution")])

    with pytest.raises(RuntimeError, match="unexpected logic bug"):
        await service._discover_candidates(req, understanding)


@pytest.mark.asyncio
async def test_discovery_timeout_uses_existing_serper_fallback():
    service = ResearchService()
    req = ResearchRequest(sector="Retail", business_goal="Reduce checkout waiting time", budget=100000, company_size="Large", employees=100)
    understanding = BusinessUnderstanding(business_problem=req.business_goal, desired_outcomes=[], processes=[], search_queries=["retail queue software"])
    service.gemini.structured = AsyncMock(side_effect=asyncio.TimeoutError())
    service._search_many = AsyncMock(return_value=[SearchResult(title="Qminder | Queue Management System", url="https://qminder.com", snippet="Checkout queue software solution")])
    service._resolve_vendor_url = AsyncMock(side_effect=lambda seed: seed)

    seeds, _ = await service._discover_candidates(req, understanding)

    assert [seed.vendor for seed in seeds] == ["Qminder"]

@pytest.mark.asyncio
async def test_invalid_credential_moves_to_next_key_without_retry():
    provider = _provider(key_count=2)
    provider._generate_with_client = AsyncMock(
        side_effect=[ProviderError("401 invalid API key"), _result()]
    )

    await provider.structured("test", BusinessUnderstanding)

    assert provider._generate_with_client.await_count == 2


@pytest.mark.asyncio
async def test_gemini_400_is_not_retried():
    provider = _provider()
    provider._generate_with_client = AsyncMock(
        side_effect=ProviderError("400 INVALID_ARGUMENT")
    )

    with pytest.raises(ProviderError, match="400"):
        await provider.structured("test", BusinessUnderstanding)

    assert provider._generate_with_client.await_count == 1


@pytest.mark.asyncio
async def test_gemini_discovery_failure_runs_one_strict_serper_expansion():
    service = ResearchService()
    req = ResearchRequest(sector="Retail", business_goal="Reduce checkout waiting time", budget=100000, company_size="Large", employees=100)
    understanding = BusinessUnderstanding(business_problem=req.business_goal, desired_outcomes=[], processes=[], search_queries=["retail queue software"])
    initial = [SearchResult(title="Queue management article", url="https://example.com/blog/queues", snippet="Blog")]
    expanded = [
        SearchResult(title="Waitwhile | Queue Management Software", url="https://waitwhile.com", snippet="Queue software platform request demo"),
        SearchResult(title="QLess | Queue Management Platform", url="https://qless.com", snippet="Retail queue software pricing"),
        SearchResult(title="Qminder | Queue Management System", url="https://qminder.com", snippet="Checkout queue software solution"),
    ]
    service.gemini.structured = AsyncMock(side_effect=RuntimeError("429 daily quota"))
    service._search_many = AsyncMock(side_effect=[initial, expanded])
    service._resolve_vendor_url = AsyncMock(side_effect=lambda seed: seed)

    seeds, _ = await service._discover_candidates(req, understanding)

    assert service._search_many.await_count == 2
    # Each expanded result is an official vendor page with a commercial
    # product signal and queue/checkout goal relevance. The fallback must keep
    # every defensible product, while still excluding the initial article.
    assert [seed.vendor for seed in seeds] == ["Waitwhile", "Qless", "Qminder"]
    assert all(seed.vendor_url.endswith(("waitwhile.com", "qless.com", "qminder.com")) for seed in seeds)


@pytest.mark.asyncio
async def test_zero_validated_products_returns_controlled_empty_result():
    service = ResearchService()
    req = ResearchRequest(sector="Retail", business_goal="Reduce checkout waiting time", budget=100000, company_size="Large", employees=100)
    understanding = BusinessUnderstanding(business_problem=req.business_goal, desired_outcomes=[], processes=[], search_queries=[])
    service._business_understanding = AsyncMock(return_value=understanding)
    service._discover_candidates = AsyncMock(return_value=([], []))
    service._validate_products_batch = AsyncMock(return_value=[])
    service._search_many = AsyncMock(return_value=[])

    result = await service.run(req)

    assert result["research_status"] == "no_defensible_products"
    assert result["recommendations"] == []
    # With no validated products, run() performs every configured bounded
    # product-intent recovery batch before returning the controlled empty
    # result. It must neither loop indefinitely nor omit a query family.
    batches = [call.args[0] for call in service._search_many.await_args_list]
    assert 1 <= len(batches) <= 3
    assert all(1 <= len(batch) <= 4 for batch in batches)
    assert [query for batch in batches for query in batch] == service._discovery_expansion_queries(req)
