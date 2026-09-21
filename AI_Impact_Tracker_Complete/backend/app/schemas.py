from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class ResearchRequest(BaseModel):
    sector: str = Field(min_length=2, max_length=120)
    business_goal: str = Field(min_length=5, max_length=1000)
    budget: float = Field(gt=0)
    company_size: Literal['Small', 'Medium', 'Large', 'Enterprise']
    employees: int = Field(gt=0)
    company_name: str | None = None
    company_country: str | None = None
    current_annual_process_cost: float | None = Field(default=None, gt=0)


class BusinessUnderstanding(BaseModel):
    business_problem: str
    desired_outcomes: list[str] = Field(default_factory=list)
    processes: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    kpis: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str = ''
    position: int = 0
    # Discovery provenance is retained for auditability.  A source URL is
    # still fetched and validated before it can support adoption or impact.
    search_provider: Literal['serper', 'bing'] = 'serper'
    domain: str = ''
    query: str = ''


class EvidenceItem(BaseModel):
    source_url: str
    source_title: str = ''
    evidence_type: str
    claim: str
    supporting_text: str = ''
    source_quality: Literal['high', 'medium', 'low'] = 'medium'
    confidence: float = Field(default=0.5, ge=0, le=1)
    search_provider: Literal['serper', 'bing'] = 'serper'
    domain: str = ''
    search_query: str = ''


class ProductCandidate(BaseModel):
    product: str
    vendor: str
    vendor_url: str
    description: str = ''
    capabilities: list[str] = Field(default_factory=list)
    sector_relevance: str = ''
    goal_relevance: str = ''
    evidence: list[EvidenceItem] = Field(default_factory=list)
    goal_fit: float = 0
    sector_fit: float = 0
    evidence_score: float = 0
    adoption_score: float = 0
    momentum_score: float = 0
    budget_score: float = 0
    sentiment_score: float | None = None
    impact_score: float = 0
    implementation_score: float = 0
    final_score: float = 0
    recommendation_confidence: float = 0
    rank: int = 0
    annual_software_cost: float | None = None
    implementation_cost: float | None = None
    currency: str = "GBP"
    pricing_basis: str = ""
    pricing_confidence: float = 0
    reviews: list[dict] = Field(default_factory=list)
    sentiment_summary: dict = Field(default_factory=dict)
    customers: list[dict] = Field(default_factory=list)
    customer_impact: list[dict] = Field(default_factory=list)
    pricing_evidence: list[dict] = Field(default_factory=list)
    evidence_coverage: dict = Field(default_factory=dict)
    risks: list[str] = Field(default_factory=list)
    value_assessment: dict = Field(default_factory=dict)


class ImpactMeasurementCreate(BaseModel):
    research_run_id: int
    kpi_name: str
    direction: Literal['lower', 'higher']
    baseline: float | None = Field(default=None, gt=0)
    target: float | None = None
    actual: float | None = None
    annual_financial_benefit: float | None = Field(default=None, ge=0)
    investment: float | None = Field(default=None, gt=0)


class ImpactMeasurementOut(BaseModel):
    id: int
    research_run_id: int
    kpi_name: str
    actual_impact_percent: float | None
    actual_roi_percent: float | None
    actual_payback_months: float | None
    measured_at: datetime
    model_config = {'from_attributes': True}
