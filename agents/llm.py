"""OpenAI-compatible LLM client.

Reads configuration from environment:
- OPENAI_BASE_URL
- OPENAI_API_KEY
- MODEL
"""
import os
from openai import OpenAI


def get_client() -> OpenAI:
    """Return an OpenAI-compatible client configured from environment."""
    base_url = os.environ.get("OPENAI_BASE_URL")
    api_key = os.environ.get("OPENAI_API_KEY", "sk-local")
    return OpenAI(base_url=base_url, api_key=api_key)


def get_model() -> str:
    """Return the model name from environment or a default."""
    return os.environ.get("MODEL", "gpt-4o-mini")
