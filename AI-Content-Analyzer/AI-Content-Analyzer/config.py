"""
Central configuration for the AI Content Analyzer & Natural Rewriter.

Every setting comes from environment variables (normally loaded from a local
`.env` file).  No secret is ever hard-coded here, printed, or written to disk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# --------------------------------------------------------------------------
# Project paths
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
REPORT_DIR = OUTPUT_DIR / "reports"

# Load `.env` from the project root if it exists (it is git-ignored).
load_dotenv(BASE_DIR / ".env")


def _get_str(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    return value.strip() if isinstance(value, str) else default


def _get_int(name: str, default: int) -> int:
    raw = _get_str(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _get_bool(name: str, default: bool = False) -> bool:
    raw = _get_str(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of the runtime configuration."""

    provider: str          # "openai" | "anthropic" | "mock"
    api_key: str           # never logged, never printed
    model_name: str
    base_url: str
    request_timeout: int   # seconds per HTTP request
    max_retries: int       # retries for transient failures
    max_chunk_chars: int   # soft size limit of one chunk sent to the model
    temperature: float
    test_mode: bool        # run the offline mock provider

    # -- helpers ----------------------------------------------------------
    @property
    def use_mock(self) -> bool:
        """True when no real model should be contacted."""
        return self.test_mode or self.provider == "mock"

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    def masked_key(self) -> str:
        """A safe, non-reversible hint used only in diagnostics."""
        if not self.api_key:
            return "(not set)"
        return f"{self.api_key[:3]}...{self.api_key[-2:]} ({len(self.api_key)} chars)"

    def describe(self) -> dict:
        """Human-readable configuration summary WITHOUT the secret value."""
        return {
            "provider": self.provider,
            "model_name": self.model_name or "(not set)",
            "base_url": self.base_url or "(provider default)",
            "api_key": self.masked_key(),
            "test_mode": self.test_mode,
            "max_chunk_chars": self.max_chunk_chars,
            "request_timeout_seconds": self.request_timeout,
            "max_retries": self.max_retries,
        }


def get_settings() -> Settings:
    """Build a Settings object from the current environment."""
    provider = _get_str("MODEL_PROVIDER", "openai").lower()
    if provider not in {"openai", "anthropic", "mock"}:
        provider = "openai"

    return Settings(
        provider=provider,
        api_key=_get_str("MODEL_API_KEY"),
        model_name=_get_str("MODEL_NAME"),
        base_url=_get_str("MODEL_BASE_URL"),
        request_timeout=_get_int("REQUEST_TIMEOUT", 120),
        max_retries=_get_int("MAX_RETRIES", 2),
        max_chunk_chars=_get_int("MAX_CHUNK_CHARS", 6000),
        temperature=float(_get_str("MODEL_TEMPERATURE", "0.3") or 0.3),
        test_mode=_get_bool("TEST_MODE", False),
    )


def ensure_directories() -> None:
    """Create the input/output folders if they are missing."""
    for folder in (INPUT_DIR, OUTPUT_DIR, REPORT_DIR):
        folder.mkdir(parents=True, exist_ok=True)


# Shared, standard disclaimer used by every report the engine produces.
DISCLAIMER = (
    "These results are linguistic and statistical INDICATORS only. They are not "
    "proof of authorship. No AI-detection method — including this one — can "
    "reliably determine whether a human or a model wrote a piece of text. "
    "Human writing is frequently flagged as AI-like and model output is "
    "frequently missed. This tool deliberately reports no accuracy percentage "
    "because no representative benchmark has been run for it, and it makes no "
    "claim that rewritten text will bypass any external detector."
)
