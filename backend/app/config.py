import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import HTTPException
from pydantic import BaseModel, Field, HttpUrl, ValidationError

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def get_api_key() -> str:
    return os.getenv("SERPAPI_API_KEY", "").strip()


class OllamaSettings(BaseModel):
    url: HttpUrl = HttpUrl("http://localhost:11434")
    model: str = Field(default="gemma3:4b", min_length=1, max_length=100)
    timeout_seconds: float = Field(default=180, ge=1, le=600, allow_inf_nan=False)


def get_ollama_settings() -> OllamaSettings:
    try:
        return OllamaSettings(
            url=os.getenv("OLLAMA_URL", "http://localhost:11434"),
            model=os.getenv("OLLAMA_MODEL", "gemma3:4b").strip(),
            timeout_seconds=os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"),
        )
    except ValidationError:
        raise HTTPException(503, "Invalid Ollama configuration. Check backend/.env.") from None
