import asyncio
from unittest.mock import AsyncMock

from app.schemas import ResearchRequest, SearchResult
from app.services.research import CandidateSeed, ResearchService


def req():
    return ResearchRequest(sector="Retail", business_goal="Reduce customer checkout waiting time", budget=100000, company_size="Large", employees=100)


def test_official_commercial_solution_is_a_candidate():
    service = ResearchService()
    seed = asyncio.run(service._resolve_commercial_identity(SearchResult(title="Retail Queue Management | Wavetec", url="https://wavetec.com/queue-management", snippet="Queue management software. Request a demo."), req()))
    assert seed and seed.vendor == "Wavetec" and "wavetec.com" in seed.vendor_url


def test_third_party_clue_resolves_to_official_identity():
    service = ResearchService()
    service._search_many = AsyncMock(return_value=[SearchResult(title="QueueAway | Queue Management Software", url="https://queueaway.com/product", snippet="Queue management platform with demo")])
    seed = asyncio.run(service._resolve_commercial_identity(SearchResult(title="QueueAway queue software", url="https://www.g2.com/products/queueaway", snippet="Queue management system"), req()))
    assert seed and seed.vendor == "QueueAway" and "queueaway.com" in seed.vendor_url


def test_blog_pdf_and_scribd_are_not_product_identities():
    service = ResearchService()
    for hit in (
        SearchResult(title="Queue software guide", url="https://vendor.com/blog/queue", snippet="software"),
        SearchResult(title="Conference queue platform", url="https://event.com/slides.pdf", snippet="platform"),
        SearchResult(title="Queue report", url="https://scribd.com/document/1", snippet="software"),
    ):
        assert asyncio.run(service._resolve_commercial_identity(hit, req())) is None


def test_commercial_system_title_attempts_identity_resolution():
    service = ResearchService()
    service._search_many = AsyncMock(return_value=[])
    asyncio.run(service._resolve_commercial_identity(SearchResult(title="Retail Queue Management System | Moviik", url="https://www.g2.com/products/moviik", snippet="Queue management software"), req()))
    assert service._search_many.await_count == 1


def test_conceptual_goal_relevance_and_canonical_deduplication():
    service = ResearchService()
    seed = CandidateSeed(product="FlowPro", vendor="FlowCo", vendor_url="https://flowco.com/product", why_relevant="")
    assert service._is_genuine_commercial_candidate(seed, "FlowPro is a customer-flow platform with real-time queue analytics and request demo.", req())[0]
    seeds = service._canonicalise_candidate_seeds([
        seed, CandidateSeed(product="FlowPro", vendor="FlowCo", vendor_url="https://flowco.com/features"),
        CandidateSeed(product="FlowVision", vendor="FlowCo", vendor_url="https://flowco.com/vision"),
    ], 8)
    assert [item.product for item in seeds] == ["FlowPro", "FlowVision"]


def test_gemini_free_fallback_accepts_commercial_queue_system():
    seeds = ResearchService()._fallback_candidate_seeds([
        SearchResult(title="Retail Queue Management System | QueueAway", url="https://queueaway.com/retail", snippet="Queue management software platform. Book demo."),
    ], 8, req())
    assert len(seeds) == 1
