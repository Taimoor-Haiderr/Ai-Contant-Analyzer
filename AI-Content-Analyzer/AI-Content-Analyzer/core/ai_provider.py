"""
AI provider abstraction.

The rest of the engine only knows about `AIProvider.complete(...)`.  Swapping
OpenAI for Anthropic, OpenRouter, Groq, Ollama or a local server is a config
change, not a code change.

Providers implemented here:
  * OpenAICompatibleProvider - any `/v1/chat/completions` endpoint
  * AnthropicProvider        - the `/v1/messages` endpoint
  * MockProvider             - offline test mode, contacts no network
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import requests

from config import Settings
from core.errors import (
    ContextLimitError,
    MissingAPIKeyError,
    ProviderError,
    ProviderTimeoutError,
    sanitize,
)

# Tasks the engine asks a provider to perform.
TASK_ANALYSIS = "analysis"
TASK_REWRITE = "rewrite"

_TEXT_BLOCK = re.compile(
    r"--- BEGIN TEXT ---\n(.*?)\n--- END TEXT ---", re.DOTALL
)


def _extract_source_text(user_prompt: str) -> str:
    """Pull the user's content back out of a prompt (used by the mock)."""
    match = _TEXT_BLOCK.search(user_prompt)
    return match.group(1) if match else user_prompt


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------
class AIProvider:
    """Interface every provider implements."""

    name = "base"
    is_mock = False

    def complete(self, system: str, user: str, task: str) -> str:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# OpenAI-compatible HTTP provider
# ---------------------------------------------------------------------------
class OpenAICompatibleProvider(AIProvider):
    """Works with OpenAI, OpenRouter, Groq, Together, LM Studio, Ollama, ..."""

    name = "openai"

    def __init__(self, settings: Settings):
        if not settings.has_api_key:
            raise MissingAPIKeyError(
                "MODEL_API_KEY is not set.",
                "Create a .env file (copy .env.example) and add your key, or set "
                "TEST_MODE=true to run the offline mock provider.",
            )
        self.settings = settings
        base = settings.base_url or "https://api.openai.com/v1"
        self.endpoint = base.rstrip("/") + "/chat/completions"
        self.model = settings.model_name or "gpt-4o-mini"

    def complete(self, system: str, user: str, task: str) -> str:
        payload = {
            "model": self.model,
            "temperature": self.settings.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        data = _post_with_retries(self.endpoint, payload, headers, self.settings)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                "The model endpoint returned an unexpected payload shape.",
                f"{type(exc).__name__}: {exc}",
            ) from exc


# ---------------------------------------------------------------------------
# Anthropic messages provider
# ---------------------------------------------------------------------------
class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self, settings: Settings):
        if not settings.has_api_key:
            raise MissingAPIKeyError(
                "MODEL_API_KEY is not set.",
                "Create a .env file (copy .env.example) and add your key, or set "
                "TEST_MODE=true to run the offline mock provider.",
            )
        self.settings = settings
        base = settings.base_url or "https://api.anthropic.com/v1"
        self.endpoint = base.rstrip("/") + "/messages"
        self.model = settings.model_name or "claude-sonnet-4-5"

    def complete(self, system: str, user: str, task: str) -> str:
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": self.settings.temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {
            "x-api-key": self.settings.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        data = _post_with_retries(self.endpoint, payload, headers, self.settings)
        try:
            parts = [
                block.get("text", "")
                for block in data["content"]
                if block.get("type") == "text"
            ]
            return "\n".join(p for p in parts if p)
        except (KeyError, TypeError) as exc:
            raise ProviderError(
                "The model endpoint returned an unexpected payload shape.",
                f"{type(exc).__name__}: {exc}",
            ) from exc


# ---------------------------------------------------------------------------
# Shared HTTP helper
# ---------------------------------------------------------------------------
def _post_with_retries(
    url: str, payload: dict, headers: dict, settings: Settings
) -> dict[str, Any]:
    """POST JSON with retries, timeouts and secret-safe error messages."""
    secret = settings.api_key
    last_error: str = ""

    for attempt in range(settings.max_retries + 1):
        try:
            response = requests.post(
                url, json=payload, headers=headers, timeout=settings.request_timeout
            )
        except requests.Timeout as exc:
            last_error = sanitize(str(exc), secret)
            if attempt < settings.max_retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise ProviderTimeoutError(
                "The model did not respond in time.",
                f"Timeout after {settings.request_timeout}s.",
            ) from exc
        except requests.RequestException as exc:
            last_error = sanitize(str(exc), secret)
            if attempt < settings.max_retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise ProviderError(
                "Could not reach the model endpoint.", last_error
            ) from exc

        if response.status_code == 200:
            try:
                return response.json()
            except ValueError as exc:
                raise ProviderError(
                    "The model endpoint returned a non-JSON body.",
                    sanitize(response.text[:400], secret),
                ) from exc

        body = sanitize(response.text[:400], secret)

        # Context/token limits are not worth retrying.
        if response.status_code in (400, 413) and _looks_like_context_error(body):
            raise ContextLimitError(
                "The request exceeded the model's context limit. "
                "Lower MAX_CHUNK_CHARS in your .env and try again.",
                body,
            )
        if response.status_code in (401, 403):
            raise ProviderError(
                "The model endpoint rejected the credentials "
                "(check MODEL_API_KEY and MODEL_BASE_URL).",
                f"HTTP {response.status_code}",
            )
        if response.status_code in (429, 500, 502, 503, 504) and attempt < settings.max_retries:
            time.sleep(2.0 * (attempt + 1))
            last_error = f"HTTP {response.status_code}: {body}"
            continue

        raise ProviderError(
            f"The model endpoint returned HTTP {response.status_code}.", body
        )

    raise ProviderError("The model request failed after retries.", last_error)


def _looks_like_context_error(body: str) -> bool:
    lowered = body.lower()
    return any(
        marker in lowered
        for marker in ("context length", "context_length", "too many tokens", "max_tokens")
    )


# ---------------------------------------------------------------------------
# Offline mock provider (TEST MODE)
# ---------------------------------------------------------------------------
class MockProvider(AIProvider):
    """
    Deterministic offline stand-in for a real model.

    It exists so the pipeline (extraction, chunking, validation, reporting,
    exporting, file safety) can be tested without an API key or network access.
    Its output is rule-based and is always labelled `"mode": "mock"` in the
    final report so it can never be mistaken for real model analysis.
    """

    name = "mock"
    is_mock = True

    # Simple, transparent phrase simplifications for the test rewrite.
    PHRASE_MAP = [
        (r"\bin order to\b", "to"),
        (r"\bdue to the fact that\b", "because"),
        (r"\bfor the purpose of\b", "for"),
        (r"\bwith regard to\b", "about"),
        (r"\bin the event that\b", "if"),
        (r"\bat this point in time\b", "now"),
        (r"\bprior to\b", "before"),
        (r"\bsubsequent to\b", "after"),
        (r"\bthe majority of\b", "most of"),
        (r"\ba large number of\b", "many"),
        (r"\butilize[sd]?\b", "use"),
        (r"\bfacilitate\b", "help"),
        (r"\bleverage\b", "use"),
        (r"\bcommence\b", "start"),
        (r"\bendeavou?r to\b", "try to"),
        (r"\bit is important to note that\s*", ""),
        (r"\bit should be noted that\s*", ""),
        (r"\bin today's fast-paced world,?\s*", ""),
        (r"\bin conclusion,\s*", "So, "),
        (r"\bfurthermore,\s*", "Also, "),
        (r"\bmoreover,\s*", "On top of that, "),
        (r"\badditionally,\s*", "Also, "),
    ]

    OVERUSED = [
        "furthermore", "moreover", "additionally", "in conclusion",
        "it is important to note", "delve", "tapestry", "landscape",
        "realm", "seamless", "robust", "leverage", "utilize",
    ]

    def __init__(self, settings: Settings | None = None):
        self.settings = settings

    def complete(self, system: str, user: str, task: str) -> str:
        text = _extract_source_text(user)
        if task == TASK_ANALYSIS:
            return json.dumps(self._analyse(text))
        if task == TASK_REWRITE:
            return json.dumps(self._rewrite(text))
        raise ProviderError(f"Mock provider does not handle task '{task}'.")

    # -- mock analysis ----------------------------------------------------
    def _analyse(self, text: str) -> dict:
        sentences = _split_sentences(text)
        words = re.findall(r"[A-Za-z']+", text)
        indicators: list[dict] = []

        lowered = text.lower()
        found = [w for w in self.OVERUSED if w in lowered]
        if found:
            indicators.append(
                {
                    "type": "Over-used connective / filler vocabulary",
                    "severity": "High" if len(found) >= 4 else "Moderate",
                    "explanation": (
                        "Phrases frequently produced by language models appear here: "
                        + ", ".join(sorted(set(found))[:6])
                        + "."
                    ),
                }
            )

        lengths = [len(re.findall(r"[A-Za-z']+", s)) for s in sentences if s.strip()]
        if len(lengths) >= 4:
            mean = sum(lengths) / len(lengths)
            variance = sum((n - mean) ** 2 for n in lengths) / len(lengths)
            spread = variance ** 0.5
            if mean and spread / mean < 0.35:
                indicators.append(
                    {
                        "type": "Uniform sentence length",
                        "severity": "Moderate",
                        "explanation": (
                            f"Sentence lengths cluster tightly around {mean:.0f} words, "
                            "which reads as mechanically even."
                        ),
                    }
                )

        if words:
            diversity = len({w.lower() for w in words}) / len(words)
            if diversity < 0.42 and len(words) > 120:
                indicators.append(
                    {
                        "type": "Narrow vocabulary range",
                        "severity": "Moderate",
                        "explanation": (
                            f"Only {diversity:.0%} of the words are unique, suggesting "
                            "repeated wording."
                        ),
                    }
                )

        openers = [s.strip().split(" ")[0].lower() for s in sentences if s.strip()]
        repeated = {o for o in openers if openers.count(o) >= 3 and len(o) > 2}
        if repeated:
            indicators.append(
                {
                    "type": "Repeated sentence openers",
                    "severity": "Low",
                    "explanation": "Several sentences begin the same way: "
                    + ", ".join(sorted(repeated)[:4])
                    + ".",
                }
            )

        flagged = []
        for sentence in sentences:
            low = sentence.lower()
            hits = [w for w in self.OVERUSED if w in low]
            if hits and len(sentence.split()) > 6:
                flagged.append(
                    {
                        "original": sentence.strip(),
                        "reason": "Contains stock connective or filler wording ("
                        + ", ".join(hits[:3])
                        + ").",
                        "indicator_type": "Generic phrasing",
                        "strength": "Moderate",
                    }
                )
            if len(flagged) >= 5:
                break

        severity_weight = sum(
            {"High": 3, "Moderate": 2, "Low": 1}.get(i["severity"], 1)
            for i in indicators
        )
        if len(words) < 60:
            likelihood, confidence = "Inconclusive", "Low"
        elif severity_weight >= 5:
            likelihood, confidence = "High indication", "Moderate"
        elif severity_weight >= 3:
            likelihood, confidence = "Moderate indication", "Moderate"
        else:
            likelihood, confidence = "Low indication", "Low"

        return {
            "overall_assessment": (
                "OFFLINE TEST MODE. This assessment comes from a small set of local "
                "heuristics, not from a language model. It is only meant to prove the "
                f"pipeline works end to end. {len(indicators)} pattern(s) were noted "
                f"across {len(sentences)} sentence(s)."
            ),
            "ai_likelihood": likelihood,
            "confidence": confidence,
            "readability": "Not measured by the mock provider; see the statistics section.",
            "indicators": indicators,
            "flagged_passages": flagged,
        }

    # -- mock rewrite -----------------------------------------------------
    def _rewrite(self, text: str) -> dict:
        paragraphs = re.split(r"\n\s*\n", text)
        changes: list[dict] = []
        rewritten_paragraphs = []

        for paragraph in paragraphs:
            new_paragraph = paragraph
            for pattern, replacement in self.PHRASE_MAP:
                for match in re.finditer(pattern, new_paragraph, flags=re.IGNORECASE):
                    snippet = match.group(0)
                    changes.append(
                        {
                            "original": snippet,
                            "rewritten": replacement or "(removed)",
                            "change_type": (
                                "Filler removal" if not replacement
                                else "Vocabulary simplification"
                            ),
                            "reason": "Replaced a wordy or stock phrase with plainer wording.",
                        }
                    )
                new_paragraph = re.sub(
                    pattern, replacement, new_paragraph, flags=re.IGNORECASE
                )
            # Tidy the spacing/capitalisation left behind by removals.
            new_paragraph = re.sub(r"\s{2,}", " ", new_paragraph).strip()
            if new_paragraph:
                new_paragraph = new_paragraph[0].upper() + new_paragraph[1:]
            rewritten_paragraphs.append(new_paragraph)

        return {
            "rewritten": "\n\n".join(rewritten_paragraphs),
            "changes": changes[:60],
            "preservation_notes": (
                "OFFLINE TEST MODE: only fixed wordy phrases were simplified. "
                "Numbers, names, dates and sentence order were left untouched. "
                "Connect a real model for genuine contextual rewriting."
            ),
        }


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.replace("\n", " "))
    return [p for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def get_provider(settings: Settings) -> AIProvider:
    """Return the provider described by the current settings."""
    if settings.use_mock:
        return MockProvider(settings)
    if settings.provider == "anthropic":
        return AnthropicProvider(settings)
    return OpenAICompatibleProvider(settings)
