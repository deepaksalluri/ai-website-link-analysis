from fastapi import FastAPI, HTTPException
from app.config import gemini_api_key, gemini_model, llm_provider, ollama_model, groq_api_key, groq_model
from app.schemas import LinkRequest, LinkResponse
from app.services.analysis_service import analyze
from app.services.llm_service import LLMError
from app.services.website_extractor import FetchError
from app.utils.validators import InvalidWebsite, validate_url

app = FastAPI(title='AI Website Link Analysis', version='1.0.0', description='Extract a public website and return evidence-conscious business and SEO suggestions.')


@app.post('/link-analysis', response_model=LinkResponse, responses={400: {'description': 'Invalid or unsafe URL'}, 502: {'description': 'Website or LLM failure'}, 503: {'description': 'Missing API configuration'}})
def link_analysis(request: LinkRequest):
    try:
        validate_url(request.url)
        provider = llm_provider()
        if provider not in ('groq', 'ollama', 'gemini'):
            raise HTTPException(503, 'LLM_PROVIDER must be groq, ollama or gemini.')
        key = groq_api_key() if provider == 'groq' else gemini_api_key() if provider == 'gemini' else ''
        if provider == 'groq' and not key:
            raise HTTPException(503, 'GROQ_API_KEY is not configured.')
        if provider == 'gemini' and not key:
            raise HTTPException(503, 'GEMINI_API_KEY is not configured.')
        model = groq_model() if provider == 'groq' else gemini_model() if provider == 'gemini' else ollama_model()
        if provider == 'groq' and model not in ('openai/gpt-oss-120b', 'openai/gpt-oss-20b'):
            raise HTTPException(503, 'GROQ_MODEL must be openai/gpt-oss-120b or openai/gpt-oss-20b.')
        if provider == 'ollama' and model not in ('qwen2.5:3b', 'qwen2.5:7b'):
            raise HTTPException(503, 'OLLAMA_MODEL must be qwen2.5:3b or qwen2.5:7b.')
        return analyze(request.url, key, model, provider)
    except InvalidWebsite as exc:
        raise HTTPException(400, str(exc)) from exc
    except (FetchError, LLMError) as exc:
        raise HTTPException(502, str(exc)) from exc
