from dataclasses import replace
from app.schemas import LinkResponse, Metadata
from app.services.website_extractor import extract_website
from app.services.llm_service import analyze_page
from app.services.competitor_service import review_competitors


def analyze(url: str, key: str, model: str, provider: str) -> LinkResponse:
    page = extract_website(url)
    groq_truncated = provider == 'groq' and len(page.text) > 8000
    if groq_truncated:
        page = replace(page, text=page.text[:8000])
    result, input_tokens, output_tokens = analyze_page(page, key, model, provider)
    result.analysis.competitor_analysis = review_competitors(
        result.analysis.competitor_analysis, result.brand.name
    )
    limitations = [
        'Only the submitted page and its redirects are fetched; no live competitor research is performed.',
        'Competitors and their attributes are unverified AI suggestions, not independently confirmed facts.',
        'Search queries are suggestions; no search volumes or rankings were measured.',
        'Page content is untrusted and AI-generated claims and recommendations need human review.',
    ]
    if result._dropped_service_count:
        limitations.append(
            f'{result._dropped_service_count} website-derived service(s) were omitted because their evidence quotes were missing or not found in the analyzed text.'
        )
    if page.truncated:
        limitations.append('Readable text was truncated to 24,000 characters during extraction.')
    if groq_truncated:
        limitations.append('Readable text was further truncated to 8,000 characters for Groq; omitted text was not analyzed.')
    return LinkResponse(success=True, website=url, brand=result.brand, analysis=result.analysis,
        metadata=Metadata(final_url=page.final_url, page_title=page.title, meta_description=page.description,
            model=model, provider=provider, extraction_scope='One server-rendered HTML page', limitations=limitations,
            input_tokens=input_tokens, output_tokens=output_tokens))
