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
    scope = 'One server-rendered HTML page'
    if page.source_kind == 'instagram_public_embed':
        scope = 'Public Instagram profile embed and available captions'
        limitations[0] = 'The submitted Instagram profile was analyzed using its public embed; no live competitor research was performed.'
        limitations.append('Only available public embed captions were analyzed; this is not the full profile or all posts. Captions may promote other businesses and must not automatically be attributed to the account owner.')
        limitations.append('The Instagram embed is undocumented and can change or be blocked; public accessibility is not guaranteed.')
    elif page.source_kind == 'social_metadata':
        scope = 'Public social page title and description only'
        limitations.append('Only the public title and description were available; the full social page and posts were not analyzed.')
    if result._platforms_added:
        limitations.append(
            'The application assigned missing platform labels ('
            + ', '.join(result._platforms_added)
            + ') to existing query suggestions after model retry; '
              'review their relevance for each platform.'
        )
    if result._dropped_service_count:
        limitations.append(
            f'{result._dropped_service_count} website-derived service(s) were omitted because their evidence quotes were missing or not found in the analyzed text.'
        )
    if page.truncated:
        limitations.append('Extracted text or individual captions were truncated during extraction.')
    if groq_truncated:
        limitations.append('Readable text was further truncated to 8,000 characters for Groq; omitted text was not analyzed.')
    return LinkResponse(success=True, website=url, brand=result.brand, analysis=result.analysis,
        metadata=Metadata(final_url=page.final_url, page_title=page.title, meta_description=page.description,
            model=model, provider=provider, extraction_scope=scope, limitations=limitations,
            input_tokens=input_tokens, output_tokens=output_tokens))
