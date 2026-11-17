"""Safeguards for competitor suggestions; does not perform external research."""
import re
from app.schemas import CompetitorAnalysis

UNVERIFIED = (
    'AI-generated suggestion only. Competitor identity, overlap, strengths and gaps '
    'have not been independently researched or verified; confirm with reliable sources.'
)


def _normalize(name: str) -> str:
    return re.sub(r'\s+', ' ', name).strip().casefold()


def review_competitors(analysis: CompetitorAnalysis, brand_name: str) -> CompetitorAnalysis:
    """Remove duplicate, empty and self-comparisons; enforce unverified labels.

    The checks improve presentation but cannot establish that an entity exists or
    competes with the brand. No network calls or evidence verification occur here.
    """
    own_name = _normalize(brand_name)
    seen = set()
    competitors = []
    for candidate in analysis.competitors:
        name = _normalize(candidate.name)
        if not name or name == own_name or name in seen:
            continue
        seen.add(name)
        competitors.append(candidate.model_copy(update={'name': candidate.name.strip(), 'caveat': UNVERIFIED}))
    note = UNVERIFIED
    if len(competitors) < 3:
        note += ' Fewer than three suggestions were returned; do not assume the list is complete.'
    return analysis.model_copy(update={'competitors': competitors, 'research_note': note})
