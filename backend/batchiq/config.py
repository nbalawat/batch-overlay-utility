"""Runtime configuration (12-factor: everything from environment variables)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    estate_timezone: str = field(default_factory=lambda: _env("BATCHIQ_TIMEZONE", "America/New_York"))
    scenario: str = field(default_factory=lambda: _env("BATCHIQ_SCENARIO", "gl-extract-abend"))
    seed: int = field(default_factory=lambda: int(_env("BATCHIQ_SEED", "7")))
    today: str = field(default_factory=lambda: _env("BATCHIQ_TODAY", ""))  # YYYY-MM-DD, blank = real date
    business_map: Path = field(default_factory=lambda: Path(_env(
        "BATCHIQ_BUSINESS_MAP", str(Path(__file__).parent / "catalog" / "business_processes.yaml"))))
    people_directory: Path = field(default_factory=lambda: Path(_env(
        "BATCHIQ_PEOPLE", str(Path(__file__).parent / "catalog" / "people.yaml"))))
    # LLM provider: auto | anthropic | openai_compatible | offline
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "auto"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "claude-opus-5-5"))
    llm_effort: str = field(default_factory=lambda: _env("LLM_EFFORT", "medium"))
    openai_base_url: str = field(default_factory=lambda: _env("OPENAI_BASE_URL", "http://localhost:11434/v1"))
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY", "not-needed"))
    correlation_min_confidence: float = field(
        default_factory=lambda: float(_env("BATCHIQ_CORRELATION_MIN_CONFIDENCE", "0.6")))
    cors_origins: str = field(default_factory=lambda: _env("BATCHIQ_CORS_ORIGINS", "*"))


settings = Settings()
