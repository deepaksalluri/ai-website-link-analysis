import json
import socket
from unittest.mock import Mock
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.schemas import LLMResult
from app.services import llm_service, website_extractor
from app.services.website_extractor import ExtractedPage, FetchError
from app.utils.validators import InvalidWebsite, resolve_public, validate_url


@pytest.fixture
def example_result():
    platforms = ['Google Search', 'Facebook', 'Instagram', 'LinkedIn', 'X']
    return {
        'brand': {'name': 'Acme Design', 'category': 'Web design', 'summary': 'A fictional web design business.', 'products_and_services': ['Web design']},
        'analysis': {
            'competitor_analysis': {'brand_overview': 'Web design studio.', 'competitors': [], 'strengths': [], 'opportunities': ['Consider a portfolio'], 'research_note': 'Unverified suggestions; no live research.'},
            'target_search_queries': [{'query': f'web design for startups {p}', 'platforms': [p], 'intent': 'Discovery', 'business_relevance': 'Website service', 'target_audience': 'Startups'} for p in platforms],
            'seo_improvements': {'primary_keyword': 'web design', 'secondary_keywords': [], 'long_tail_keywords': [], 'business_keywords': [], 'recommended_title': 'Web design | Acme', 'meta_description': 'Web design for startups.', 'supporting_content': ['Portfolio page']},
            'top_services': [{'name': 'Web design', 'description': 'Websites', 'target_industry': 'General', 'target_customer': 'Startups', 'main_benefit': 'Online presence', 'source_type': 'website', 'evidence_quote': 'Web design for startups'}],
            'target_audience': {'primary_audience': ['Startups'], 'secondary_audience': [], 'industries': [], 'business_types': ['Startups'], 'customer_profiles': [], 'geographical_focus': 'Unknown', 'customer_needs': ['A website'], 'customer_interests': [], 'recommended_segments': ['Startups']},
        },
    }


@pytest.fixture
def page():
    return ExtractedPage('https://example.com/', 'Acme Design', '', 'Web design for startups. ' * 10, False)


@pytest.mark.parametrize('url', ['ftp://example.com', 'http://localhost', 'http://user:pass@example.com', 'http://example.com:8080', 'http://example.com\\@127.0.0.1', 'http://example.com\n'])
def test_url_validation(url):
    with pytest.raises(InvalidWebsite):
        validate_url(url)


@pytest.mark.parametrize('ip', ['127.0.0.1', '10.0.0.2', '169.254.169.254', '::1', '::ffff:127.0.0.1', '224.0.0.1'])
def test_block_nonpublic_dns(monkeypatch, ip):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 80))])
    with pytest.raises(InvalidWebsite):
        resolve_public('example.com', 80)


def test_block_mixed_dns(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: [(2, 1, 6, '', ('8.8.8.8', 80)), (2, 1, 6, '', ('10.1.1.1', 80))])
    with pytest.raises(InvalidWebsite):
        resolve_public('example.com', 80)


def test_pins_connection_to_checked_address(monkeypatch):
    captured = {}
    monkeypatch.setattr(website_extractor, 'resolve_public', lambda host, port: ['8.8.8.8'])
    class Conn:
        def __init__(self, host, port, ip):
            captured.update(host=host, port=port, ip=ip)
        def request(self, method, path, headers):
            captured.update(path=path, headers=headers)
        def getresponse(self):
            response = Mock(status=200)
            response.getheader.side_effect = lambda key, default=None: {'Content-Type': 'text/html', 'Content-Encoding': 'identity'}.get(key, default)
            response.headers.get_content_charset.return_value = 'utf-8'
            response.read.return_value = b'<html>ok</html>'
            return response
        def close(self): pass
    monkeypatch.setattr(website_extractor, 'PinnedHTTPSConnection', Conn)
    website_extractor._fetch_once('https://example.com/test')
    assert (captured['host'], captured['ip'], captured['headers']['Host']) == ('example.com', '8.8.8.8', 'example.com')


def test_redirect_revalidated(monkeypatch):
    # Keep the real fetch validation for the redirected destination; stub only the first network hop.
    original = website_extractor._fetch_once
    def fake(url):
        if url == 'https://example.com/':
            return 302, 'http://localhost/private', None
        return original(url)
    monkeypatch.setattr(website_extractor, '_fetch_once', fake)
    with pytest.raises(InvalidWebsite):
        website_extractor.extract_website('https://example.com/')


def test_extraction_removes_boilerplate_and_duplicates(monkeypatch):
    html = '<title>Studio</title><meta name="description" content="Websites"><nav>MENU</nav><script>evil()</script><main>' + '<p>Website design for small businesses and startups.</p>' * 4 + '<p>We help clients build accessible websites with useful landing pages and good design.</p></main>'
    monkeypatch.setattr(website_extractor, '_fetch_once', lambda url: (200, None, html))
    data = website_extractor.extract_website('https://example.com')
    assert data.title == 'Studio' and data.description == 'Websites'
    assert 'MENU' not in data.text and 'evil' not in data.text
    assert data.text.count('Website design for small businesses') == 1


def test_invalid_website_or_no_key(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.setenv('LLM_PROVIDER', 'gemini')
    client = TestClient(app)
    assert client.post('/link-analysis', json={'url': 'file:///etc/passwd'}).status_code == 400
    assert client.post('/link-analysis', json={'url': 'https://example.com'}).status_code == 503
    assert client.post('/link-analysis', json={}).status_code == 422


def test_endpoint_complete_response(monkeypatch, page, example_result):
    monkeypatch.setenv('LLM_PROVIDER', 'gemini')
    monkeypatch.setenv('GEMINI_API_KEY', 'test-only')
    monkeypatch.setattr('app.services.analysis_service.extract_website', lambda url: page)
    monkeypatch.setattr('app.services.analysis_service.analyze_page', lambda *a: (LLMResult.model_validate(example_result), 200, 100))
    response = TestClient(app).post('/link-analysis', json={'url': 'https://example.com'})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['success'] is True and len(body['analysis']['target_search_queries']) == 5
    assert body['metadata']['input_tokens'] == 200
    assert len(body['analysis']) == 5


def test_fetch_error_is_handled(monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER', 'gemini')
    monkeypatch.setenv('GEMINI_API_KEY', 'test-only')
    monkeypatch.setattr('app.services.analysis_service.extract_website', lambda url: (_ for _ in ()).throw(FetchError('Website unavailable.')))
    response = TestClient(app).post('/link-analysis', json={'url': 'https://example.com'})
    assert response.status_code == 502 and response.json()['detail'] == 'Website unavailable.'


def mock_google(monkeypatch, body, status=200):
    response = httpx.Response(status, json=body)
    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, headers, json):
            assert ':generateContent' in url and 'responseFormat' in json['generationConfig']
            assert headers['x-goog-api-key'] == 'secret'
            return response
    monkeypatch.setattr(llm_service.httpx, 'Client', FakeClient)


def test_provider_json_and_usage(monkeypatch, page, example_result):
    mock_google(monkeypatch, {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(example_result)}]}}], 'usageMetadata': {'promptTokenCount': 1000, 'candidatesTokenCount': 900, 'thoughtsTokenCount': 100}})
    result, inputs, outputs = llm_service.analyze_page(page, 'secret', 'gemini-3.5-flash-lite')
    assert result.brand.name == 'Acme Design' and (inputs, outputs) == (1000, 1000)


def test_provider_drops_fake_evidence(monkeypatch, page, example_result):
    example_result['analysis']['top_services'][0]['evidence_quote'] = 'Invented claim'
    mock_google(monkeypatch, {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(example_result)}]}}]})
    result, _, _ = llm_service.analyze_page(page, 'secret', 'gemini-3.5-flash-lite')
    assert result.analysis.top_services == []
    assert result._dropped_service_count == 1


def test_provider_invalid_output_and_quota(monkeypatch, page):
    mock_google(monkeypatch, {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': '{}'}]}}]})
    with pytest.raises(llm_service.LLMError, match='invalid'):
        llm_service.analyze_page(page, 'secret', 'gemini-3.5-flash-lite')
    mock_google(monkeypatch, {}, 429)
    with pytest.raises(llm_service.LLMError, match='quota'):
        llm_service.analyze_page(page, 'secret', 'gemini-3.5-flash-lite')


def test_ollama_local_json_and_usage(monkeypatch, page, example_result):
    data = {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps(example_result)}, 'prompt_eval_count': 200, 'eval_count': 300}
    class LocalClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, json):
            assert url == 'http://127.0.0.1:11434/api/chat'
            assert json['model'] == 'qwen2.5:3b' and json['format']['type'] == 'object'
            return httpx.Response(200, json=data)
    monkeypatch.setattr(llm_service.httpx, 'Client', LocalClient)
    result, inputs, outputs = llm_service.analyze_page(page, '', 'qwen2.5:3b', 'ollama')
    assert result.brand.name == 'Acme Design' and (inputs, outputs) == (200, 300)


def test_ollama_rejects_cloud_models(page):
    with pytest.raises(llm_service.LLMError, match='local model'):
        llm_service.analyze_page(page, '', 'some-cloud-model', 'ollama')


def test_ollama_without_key_endpoint(monkeypatch, page, example_result):
    monkeypatch.setenv('LLM_PROVIDER', 'ollama')
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.setattr('app.services.analysis_service.extract_website', lambda url: page)
    def fake(page, key, model, provider):
        assert key == '' and provider == 'ollama' and model == 'qwen2.5:3b'
        return LLMResult.model_validate(example_result), 200, 100
    monkeypatch.setattr('app.services.analysis_service.analyze_page', fake)
    body = TestClient(app).post('/link-analysis', json={'url': 'https://example.com'}).json()
    assert body['metadata']['provider'] == 'ollama'


def test_ollama_missing_or_incomplete_response(monkeypatch, page):
    class LocalClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, json): return httpx.Response(404, json={'error': 'model not found'})
    monkeypatch.setattr(llm_service.httpx, 'Client', LocalClient)
    with pytest.raises(llm_service.LLMError, match='ollama pull'):
        llm_service.analyze_page(page, '', 'qwen2.5:3b', 'ollama')


def test_competitor_service_deduplicates_and_enforces_caveats():
    from app.services.competitor_service import review_competitors
    from app.schemas import CompetitorAnalysis
    def competitor(name):
        return {'name': name, 'overlap': 'Possible overlap', 'strengths': [],
                'weaknesses_or_gaps': [], 'caveat': 'Verified fact'}
    data = CompetitorAnalysis.model_validate({
        'brand_overview': 'Example business',
        'competitors': [competitor('Acme Design'), competitor(' Rival Inc '), competitor('rival inc'), competitor('')],
        'strengths': [], 'opportunities': [], 'research_note': 'Confirmed by independent research',
    })
    checked = review_competitors(data, 'acme design')
    assert len(checked.competitors) == 1
    assert checked.competitors[0].name == 'Rival Inc'
    assert 'not been independently' in checked.competitors[0].caveat
    assert 'Fewer than three' in checked.research_note
    assert 'Confirmed by independent research' not in checked.research_note


def test_query_validation_rejects_duplicates_and_empty_platforms(example_result):
    from pydantic import ValidationError
    example_result['analysis']['target_search_queries'][1]['query'] = example_result['analysis']['target_search_queries'][0]['query']
    with pytest.raises(ValidationError, match='distinct'):
        LLMResult.model_validate(example_result)
    example_result['analysis']['target_search_queries'][1]['query'] = 'Different query'
    example_result['analysis']['target_search_queries'][1]['platforms'] = []
    with pytest.raises(ValidationError, match='platforms'):
        LLMResult.model_validate(example_result)


def test_gemini_503_falls_back_to_json_and_validates(monkeypatch, page, example_result):
    requests = []
    class FallbackClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, headers, json):
            requests.append(json)
            if len(requests) == 1:
                return httpx.Response(503, json={'error': {'status': 'UNAVAILABLE'}})
            return httpx.Response(200, json={
                'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': __import__('json').dumps(example_result)}]}}],
                'usageMetadata': {'promptTokenCount': 300, 'candidatesTokenCount': 400}
            })
    monkeypatch.setattr(llm_service.httpx, 'Client', FallbackClient)
    result, inputs, outputs = llm_service.analyze_page(page, 'secret', 'gemini-3.5-flash-lite', 'gemini')
    assert result.brand.name == 'Acme Design' and (inputs, outputs) == (300, 400)
    assert len(requests) == 2
    assert 'responseFormat' in requests[0]['generationConfig']
    assert requests[1]['generationConfig'] == {'responseMimeType': 'application/json'}
    assert 'required output JSON schema' in requests[1]['systemInstruction']['parts'][0]['text']


def test_gemini_no_fallback_on_quota(monkeypatch, page):
    calls = []
    class QuotaClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, headers, json):
            calls.append(json)
            return httpx.Response(429, json={'error': {'status': 'RESOURCE_EXHAUSTED'}})
    monkeypatch.setattr(llm_service.httpx, 'Client', QuotaClient)
    with pytest.raises(llm_service.LLMError, match='quota'):
        llm_service.analyze_page(page, 'secret', 'gemini-3.5-flash-lite', 'gemini')
    assert len(calls) == 1


def test_gemini_reports_when_schema_and_json_are_unavailable(monkeypatch, page):
    calls = []
    class UnavailableClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, headers, json):
            calls.append(json)
            return httpx.Response(503, json={'error': {'status': 'UNAVAILABLE'}})
    monkeypatch.setattr(llm_service.httpx, 'Client', UnavailableClient)
    with pytest.raises(llm_service.LLMError, match='both structured and JSON-mode'):
        llm_service.analyze_page(page, 'secret', 'gemini-3.5-flash-lite', 'gemini')
    assert len(calls) == 2


def test_gemini_fallback_rejects_bad_output(monkeypatch, page):
    calls = []
    class BadJsonClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, headers, json):
            calls.append(json)
            if len(calls) == 1:
                return httpx.Response(503)
            return httpx.Response(200, json={'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': '{}'}]}}]})
    monkeypatch.setattr(llm_service.httpx, 'Client', BadJsonClient)
    with pytest.raises(llm_service.LLMError, match='invalid or incomplete'):
        llm_service.analyze_page(page, 'secret', 'gemini-3.5-flash-lite', 'gemini')
    assert len(calls) == 2


def test_groq_schema_and_usage(monkeypatch, page, example_result):
    class GroqClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, headers, json):
            assert url == 'https://api.groq.com/openai/v1/chat/completions'
            assert headers['Authorization'] == 'Bearer test-key'
            assert json['model'] == 'openai/gpt-oss-120b'
            assert json['response_format']['json_schema']['strict'] is True
            assert json['response_format']['json_schema']['schema']['additionalProperties'] is False
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': __import__('json').dumps(example_result)}}], 'usage': {'prompt_tokens': 500, 'completion_tokens': 1000}})
    monkeypatch.setattr(llm_service.httpx, 'Client', GroqClient)
    result, inputs, outputs = llm_service.analyze_page(page, 'test-key', 'openai/gpt-oss-120b', 'groq')
    assert result.brand.name == 'Acme Design' and (inputs, outputs) == (500, 1000)


def test_groq_errors_and_output_validation(monkeypatch, page):
    class GroqClient:
        status = 429
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, headers, json):
            if self.status == 200:
                return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]})
            return httpx.Response(self.status, json={})
    monkeypatch.setattr(llm_service.httpx, 'Client', GroqClient)
    with pytest.raises(llm_service.LLMError, match='quota'):
        llm_service.analyze_page(page, 'test-key', 'openai/gpt-oss-120b', 'groq')
    GroqClient.status = 401
    with pytest.raises(llm_service.LLMError, match='authentication'):
        llm_service.analyze_page(page, 'test-key', 'openai/gpt-oss-120b', 'groq')
    GroqClient.status = 200
    with pytest.raises(llm_service.LLMError, match='invalid or incomplete'):
        llm_service.analyze_page(page, 'test-key', 'openai/gpt-oss-120b', 'groq')


def test_groq_missing_key_and_route(monkeypatch, page, example_result):
    monkeypatch.setenv('LLM_PROVIDER', 'groq')
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    client = TestClient(app)
    assert client.post('/link-analysis', json={'url': 'https://example.com'}).status_code == 503
    monkeypatch.setenv('GROQ_API_KEY', 'test-only')
    monkeypatch.setattr('app.services.analysis_service.extract_website', lambda url: page)
    def fake(page, key, model, provider):
        assert key == 'test-only' and provider == 'groq' and model == 'openai/gpt-oss-120b'
        return LLMResult.model_validate(example_result), 200, 100
    monkeypatch.setattr('app.services.analysis_service.analyze_page', fake)
    body = client.post('/link-analysis', json={'url': 'https://example.com'}).json()
    assert body['metadata']['provider'] == 'groq'


def test_groq_text_truncation_labeled(monkeypatch, page, example_result):
    from dataclasses import replace
    monkeypatch.setenv('LLM_PROVIDER', 'groq')
    monkeypatch.setenv('GROQ_API_KEY', 'test-only')
    long_page = replace(page, text=page.text * 100)
    monkeypatch.setattr('app.services.analysis_service.extract_website', lambda url: long_page)
    def fake(page, key, model, provider):
        assert len(page.text) == 8000
        return LLMResult.model_validate(example_result), 200, 100
    monkeypatch.setattr('app.services.analysis_service.analyze_page', fake)
    body = TestClient(app).post('/link-analysis', json={'url': 'https://example.com'}).json()
    assert any('8,000' in item for item in body['metadata']['limitations'])


def test_groq_drops_unsupported_quotes_but_keeps_supported_and_inferred(page, example_result):
    from copy import deepcopy
    valid = example_result['analysis']['top_services'][0]
    fake = deepcopy(valid)
    fake.update(name='Fabricated Service', evidence_quote='Text not on the page')
    missing = deepcopy(valid)
    missing.update(name='Missing evidence', evidence_quote=None)
    inferred = deepcopy(valid)
    inferred.update(name='Suggested Blog', source_type='inferred_recommendation', evidence_quote=None)
    example_result['analysis']['top_services'] = [valid, fake, missing, inferred]
    result = llm_service._validate_result(page, json.dumps(example_result))
    assert [s.name for s in result.analysis.top_services] == ['Web design', 'Suggested Blog']
    assert result._dropped_service_count == 2
    assert '_dropped_service_count' not in result.model_dump()


def test_omitted_service_count_is_returned_in_metadata(monkeypatch, page, example_result):
    monkeypatch.setenv('LLM_PROVIDER', 'groq')
    monkeypatch.setenv('GROQ_API_KEY', 'test-only')
    monkeypatch.setattr('app.services.analysis_service.extract_website', lambda url: page)
    example_result['analysis']['top_services'][0]['evidence_quote'] = 'Not in page'
    parsed = llm_service._validate_result(page, json.dumps(example_result))
    monkeypatch.setattr('app.services.analysis_service.analyze_page', lambda *args: (parsed, 200, 100))
    response = TestClient(app).post('/link-analysis', json={'url': 'https://example.com'})
    assert response.status_code == 200
    assert response.json()['analysis']['top_services'] == []
    assert any('1 website-derived service(s) were omitted' in note for note in response.json()['metadata']['limitations'])
