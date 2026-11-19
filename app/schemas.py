from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class LinkRequest(StrictModel):
    url: str = Field(min_length=1, max_length=2048)


class Brand(StrictModel):
    name: str
    category: str
    summary: str
    products_and_services: list[str]


class Competitor(StrictModel):
    name: str
    overlap: str
    strengths: list[str]
    weaknesses_or_gaps: list[str]
    caveat: str


class CompetitorAnalysis(StrictModel):
    brand_overview: str
    competitors: list[Competitor]
    strengths: list[str]
    opportunities: list[str]
    research_note: str


Platform = Literal['Google Search', 'Facebook', 'Instagram', 'LinkedIn', 'X']


class SearchQuery(StrictModel):
    query: str
    platforms: list[Platform]
    intent: str
    business_relevance: str
    target_audience: str


class SEO(StrictModel):
    primary_keyword: str
    secondary_keywords: list[str]
    long_tail_keywords: list[str]
    business_keywords: list[str]
    recommended_title: str
    meta_description: str
    supporting_content: list[str]


class Service(StrictModel):
    name: str
    description: str
    target_industry: str
    target_customer: str
    main_benefit: str
    source_type: Literal['website', 'inferred_recommendation']
    evidence_quote: str | None


class Audience(StrictModel):
    primary_audience: list[str]
    secondary_audience: list[str]
    industries: list[str]
    business_types: list[str]
    customer_profiles: list[str]
    geographical_focus: str
    customer_needs: list[str]
    customer_interests: list[str]
    recommended_segments: list[str]


class Analysis(StrictModel):
    competitor_analysis: CompetitorAnalysis
    target_search_queries: list[SearchQuery]
    seo_improvements: SEO
    top_services: list[Service]
    target_audience: Audience

    @model_validator(mode='after')
    def check_contract(self):
        if len(self.target_search_queries) != 5:
            raise ValueError('Exactly five search queries are required')
        queries = [q.query.strip().casefold() for q in self.target_search_queries]
        if any(not q for q in queries) or len(set(queries)) != 5:
            raise ValueError('Search queries must be non-empty and distinct')
        if any(not q.platforms or not q.intent.strip() or not q.business_relevance.strip() or not q.target_audience.strip() for q in self.target_search_queries):
            raise ValueError('Each search query requires platforms, intent, relevance and audience')
        if {p for q in self.target_search_queries for p in q.platforms} != {'Google Search', 'Facebook', 'Instagram', 'LinkedIn', 'X'}:
            raise ValueError('All five platforms must be covered')
        if len(self.top_services) > 5:
            raise ValueError('At most five services are allowed')
        for service in self.top_services:
            if service.source_type == 'inferred_recommendation' and service.evidence_quote is not None:
                raise ValueError('Inferred services cannot claim website evidence')
        return self


class LLMResult(StrictModel):
    _dropped_service_count: int = PrivateAttr(default=0)
    _platforms_added: list[str] = PrivateAttr(default_factory=list)
    brand: Brand
    analysis: Analysis


class Metadata(StrictModel):
    final_url: str
    page_title: str
    meta_description: str
    model: str
    provider: str
    extraction_scope: str
    limitations: list[str]
    input_tokens: int | None
    output_tokens: int | None


class LinkResponse(StrictModel):
    success: Literal[True]
    website: str
    brand: Brand
    analysis: Analysis
    metadata: Metadata
