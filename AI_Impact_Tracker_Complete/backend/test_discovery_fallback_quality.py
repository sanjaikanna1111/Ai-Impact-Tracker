from app.schemas import ResearchRequest, SearchResult
from app.services.research import ResearchService


def request():
    return ResearchRequest(
        sector="Retail", business_goal="Reduce queue waiting time",
        budget=1000, company_size="Large", employees=100,
    )


def fallback(*hits):
    return ResearchService()._fallback_candidate_seeds(list(hits), 8, request())


def test_social_and_editorial_results_never_become_products():
    seeds = fallback(
        SearchResult(title="Person Detection for Queue Management", url="https://facebook.com/post/1", snippet="Queue software"),
        SearchResult(title="Top 10 Queue Providers", url="https://example.com/top-10-queue-providers", snippet="Queue software platforms"),
        SearchResult(title="Computer Vision", url="https://vendor.example/blog/computer-vision", snippet="Queue solution"),
    )
    assert seeds == []


def test_vendor_product_page_can_become_one_deduplicated_seed():
    seeds = fallback(
        SearchResult(title="Waitwhile | Queue Management Software", url="https://waitwhile.com/", snippet="Queue management software. Request demo."),
        SearchResult(title="Waitwhile - Queue Platform", url="https://waitwhile.com/features", snippet="Queue software features and pricing."),
    )
    assert len(seeds) == 1
    assert seeds[0].product == "Waitwhile"
    assert seeds[0].vendor_url.startswith("https://waitwhile.com")


def test_vendor_case_study_does_not_become_product_name():
    seeds = fallback(
        SearchResult(title="How QueuePro reduced waiting times for Retailer", url="https://acme.example/case-study/retailer", snippet="QueuePro platform customer story"),
    )
    assert seeds == []
