import os
from dotenv import load_dotenv

load_dotenv()


def llm_provider() -> str:
    return os.getenv('LLM_PROVIDER', 'groq').strip().lower()


def ollama_model() -> str:
    return os.getenv('OLLAMA_MODEL', 'qwen2.5:3b').strip()


def gemini_api_key() -> str:
    return os.getenv('GEMINI_API_KEY', '').strip()


def gemini_model() -> str:
    return os.getenv('GEMINI_MODEL', 'gemini-3.5-flash-lite').strip()


def groq_api_key() -> str:
    return os.getenv('GROQ_API_KEY', '').strip()


def groq_model() -> str:
    return os.getenv('GROQ_MODEL', 'openai/gpt-oss-120b').strip()
