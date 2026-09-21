import asyncio

from app.schemas import SearchResult
from app.services.research import ResearchService


def test_cross_provider_results_are_deduplicated_by_canonical_url():
    service = ResearchService()
    results = service._merge_search_results(
        [SearchResult(
            title="Customer story", url="https://www.example.com/story/?utm_source=search",
            search_provider="serper", domain="example.com", query="Product customer",
        )],
        [SearchResult(
            title="Publisher citation", url="https://example.com/story",
            search_provider="bing", domain="example.com", query="Product customer",
        )],
    )

    assert len(results) == 1
    assert results[0].search_provider == "serper"
    assert results[0].domain == "example.com"
    assert results[0].query == "Product customer"


def test_customer_queries_do_not_repeat_product_when_vendor_matches():
    service = ResearchService()
    product_vendor = '"Qminder"'
    queries = [f"{product_vendor} customer", f"{product_vendor} case study"]

    assert all(query.count('"Qminder"') == 1 for query in queries)


def test_unconfigured_bing_keeps_serper_customer_results():
    service = ResearchService()

    async def serper_only(queries, num=10):
        return [SearchResult(title="Case study", url="https://publisher.test/case", query=queries[0])]

    service._search_many = serper_only
    # An unconfigured provider does not make a network request and cannot fail research.
    results = asyncio.run(service._customer_search_many(['"Product" customer']))

    assert len(results) == 1
    assert results[0].url == "https://publisher.test/case"
