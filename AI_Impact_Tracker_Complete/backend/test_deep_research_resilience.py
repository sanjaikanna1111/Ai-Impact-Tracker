from unittest.mock import AsyncMock

import pytest

from app.schemas import ProductCandidate, ResearchRequest
from app.services.research import CompactDeepAnalysis, CompactDeepProductItem, ResearchService


def request():
    return ResearchRequest(sector="Retail", business_goal="Reduce checkout waiting time", budget=1000, company_size="Large", employees=100)


def candidate(name="Product"):
    return ProductCandidate(product=name, vendor="Vendor", vendor_url="https://vendor.example")


def test_compact_pack_enforces_source_and_excerpt_limits():
    service = ResearchService()
    hits = [type("Hit", (), {"url": f"https://reviews{i}.example/{i}", "title": "Product Vendor review", "snippet": "x" * 2000})() for i in range(20)]
    pack = service._build_compact_evidence_pack({"domain": "vendor.example", "general_pages": [], "evidence_hits": hits, "review_hits": hits})
    assert len(pack["general_evidence"]) == 8
    assert len(pack["review_sources"]) == 12
    assert all(len(row["text"]) <= 800 for row in pack["review_sources"])


@pytest.mark.asyncio
async def test_quota_fallback_preserves_review_evidence():
    service = ResearchService()
    row = {"source_url": "https://g2.com/product", "source_title": "Review", "platform": "G2", "snippet": "Review", "content_excerpt": "Useful review", "sentiment": "unclassified", "summary": "", "confidence": 0.0}
    bundle = {"domain": "vendor.example", "evidence_hits": [], "retained_source_evidence": [], "review_records": [row]}
    service._enrich_customer_financials = AsyncMock()
    result = await service._apply_deep_fallback(request(), candidate(), bundle, "unavailable_due_to_llm_quota")
    assert result.reviews[0]["source_url"] == row["source_url"]
    assert result.sentiment_summary["sentiment_analysis_status"] == "unavailable_due_to_llm_quota"


@pytest.mark.asyncio
async def test_first_product_failure_does_not_prevent_next_product_analysis():
    service = ResearchService()
    first, second = candidate("One"), candidate("Two")
    def bundle(item):
        return {"candidate": item, "domain": "vendor.example", "evidence_hits": [], "review_hits": [], "general_pages": [], "review_pages": [], "retained_source_evidence": [], "review_records": []}
    service._collect_deep_bundle = AsyncMock(side_effect=[bundle(first), bundle(second)])
    service._apply_deep_fallback = AsyncMock(side_effect=lambda req, item, bundle, status: item)
    service._apply_deep_analysis = AsyncMock(side_effect=lambda req, item, deep, bundle: item)
    service.gemini.structured = AsyncMock(side_effect=[RuntimeError("temporary failure"), CompactDeepAnalysis(products=[CompactDeepProductItem(product="Two", vendor="Vendor")])])
    result = await service._deep_products_batch(request(), [first, second])
    assert len(result) == 2
    assert service.gemini.structured.await_count == 2
