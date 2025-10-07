import os
from functools import lru_cache
from pathlib import Path

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore

from pydantic import BaseModel

# Load environment variables from .env if possible
if load_dotenv is not None:
    load_dotenv()
else:
    # Fallback minimal loader: parse KEY=VALUE lines from nearest .env
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    os.environ.setdefault(key, value)
        except Exception:
            pass


class Settings(BaseModel):
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_base: str = os.getenv("OPENROUTER_BASE", "https://openrouter.ai/api/v1")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o")
    debug: bool = os.getenv("APP_DEBUG", "false").lower() in {"1", "true", "yes"}


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if not s.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    return s
