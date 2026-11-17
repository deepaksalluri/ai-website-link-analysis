# AI Website Link Analysis API

A FastAPI service that extracts content from a public website and generates structured business and marketing insights using an LLM. Groq-hosted GPT-OSS 120B is the default model; Gemini and Ollama are available as alternatives.

## Features

- **Competitor analysis:** brand positioning and suggested competitors, clearly labeled as unverified.
- **Search queries:** five distinct queries covering Google Search, Facebook, Instagram, LinkedIn, and X.
- **SEO recommendations:** keywords, a suggested title and meta description, and content ideas.
- **Products and services:** up to five entries, with evidence checks for website-derived claims.
- **Target audience:** potential customer segments, industries, needs, and interests.
- **Safety and validation:** public URL checks, redirect revalidation, structured response validation, and descriptive errors.

## Tech stack

Python · FastAPI · Pydantic · HTTPX · Beautiful Soup · Groq API · pytest

## Project structure

```text
ai-link-analysis/
├── app/
│   ├── main.py                # FastAPI route and error mapping
│   ├── config.py              # Environment settings
│   ├── schemas.py             # Request, LLM and response contracts
│   ├── services/
│   │   ├── website_extractor.py      # Public IP-pinned HTTP(S) fetch and extraction
│   │   ├── llm_service.py            # Groq / Ollama / Gemini structured output and evidence validation
│   │   ├── analysis_service.py       # Orchestrates the pipeline
│   │   └── competitor_service.py     # Deduplicates and labels unverified competitor suggestions
│   └── utils/
│       └── validators.py          # URL validation and public DNS checks
├── tests/
│   └── test_link_analysis.py
├── .env.example
├── requirements.txt
└── README.md
```

## Getting started

### Prerequisites

- Python 3.10 or later
- Internet access
- A [Groq API key](https://console.groq.com/keys) with access to `openai/gpt-oss-120b`

Groq offers a free plan subject to account eligibility and usage limits. Check your account's quota and billing settings before running the application; paid usage can incur charges.

### Installation

From the project root, on Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Set the following values in `.env`:

```dotenv
LLM_PROVIDER=groq
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-120b
```

Save the file and start the API:

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 4000
```

On macOS/Linux, create and activate a virtual environment with `python3 -m venv .venv` and `source .venv/bin/activate`, install with `python -m pip install -r requirements.txt`, copy `.env.example` to `.env`, then run `python -m uvicorn app.main:app --host 0.0.0.0 --port 4000`.

Open the interactive API documentation at **http://localhost:4000/docs**.

> Never commit `.env` or share your API key. The sample `.env.example` must contain placeholders only.

## API usage

### `POST /link-analysis`

**Request**

```json
{
  "url": "https://www.python.org/"
}
```

Or run:

```bash
curl -X POST "http://localhost:4000/link-analysis" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.python.org/"}'
```

The JSON response contains a brand overview, the five analysis sections, and metadata describing the extraction and its limitations. Use Swagger UI to inspect the complete response.

**Common errors:** `400` for a rejected URL, `422` for an invalid request body, `502` for a website or LLM failure, and `503` for missing or invalid provider configuration. Error responses include a `detail` message.

## Screenshots


### Successful API request
![Swagger request and successful response](screenshots\Screenshot%202026-11-18%20001042.png)

### Analysis output 1
![Website analysis response sections](screenshots\Screenshot%202026-11-18%20001100.png)

### Analysis output 2
![Website analysis response sections](screenshots\Screenshot%202026-11-18%20001136.png)

### Terminal Response
![Terminal results](screenshots\Screenshot%202026-11-18%20001225.png)


## Running tests

```powershell
.\.venv\Scripts\python -m pytest -q
```

On macOS/Linux with the virtual environment active, run `python -m pytest -q`. Tests mock network and model boundaries; they do not replace a live API check. Run them again after any code change.

## LLM comparison

Indicative standard text API prices in USD per million tokens; availability and pricing can change. Model quality and application latency have not been benchmarked for this project.

| Model | Input / output price | Structured output | Assessment |
|---|---:|---|---|
| [Groq GPT-OSS 120B](https://console.groq.com/docs/model/openai/gpt-oss-120b) | $0.15 / $0.60 | Yes | Default hosted model; eligible free-plan usage is subject to limits. |
| [Gemini 3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/pricing) | $0.30 / $2.50 | Yes | Implemented alternative; free-tier eligibility and quotas vary. |
| [Claude Haiku 5.5](https://platform.claude.com/docs/en/models/haiku-5-5/overview) | From $0.10 / $0.50 | Yes | Research comparison; not integrated. |

Groq was selected for hosted inference and schema-constrained output without a local model download. For illustration, 6,000 input and 2,000 output tokens at the listed Groq paid rates cost approximately **$0.0021** before retries or other charges; this is not a measured average. Ollama with Qwen2.5 is also supported as an optional local alternative and requires a model download. Gemini and Ollama can be configured through `.env.example`; providers are not switched automatically.

## Limitations and security

- The application analyzes one server-rendered HTML page; JavaScript-heavy or restricted sites may provide incomplete content.
- Competitor names and attributes are unverified AI suggestions, not independent research. No search volumes or ranking measurements are supplied.
- Website-derived service quotes are checked against extracted text; unsupported entries are omitted. Matching a quote does not prove the broader claim is true. AI-generated insights require human review.
- Public URL validation, IP pinning, and redirect checks reduce SSRF risk. Production deployment needs additional controls, including network egress restrictions, authentication, and rate limiting.
- Extracted content is sent to the configured provider. Analyze only public content you have permission to process.

## Publishing

This project intentionally follows the requested file structure and does not include a `.gitignore`. Before staging, configure local exclusions for `.env`, virtual environments, and caches, and review `git status` and `git diff --cached --name-only`. Local Git exclusions do not apply to other clones. If a key is exposed, revoke or rotate it and remove it from Git history before publishing.
