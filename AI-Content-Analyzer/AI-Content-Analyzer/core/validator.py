"""
Model-response validation.

The model is never trusted.  Every structured response goes through:

    raw text -> strip fences -> balanced-JSON scan -> repair -> json.loads
             -> schema coercion -> typed result

If the response cannot be recovered, a `ModelResponseError` is raised so the
caller can retry or surface a controlled failure.  The engine never invents an
analysis to paper over a failed model call.
"""

from __future__ import annotations

import json
import re

from core.errors import ModelResponseError

LIKELIHOOD_VALUES = [
    "Low indication",
    "Moderate indication",
    "High indication",
    "Inconclusive",
]
LEVELS = ["Low", "Moderate", "High"]

CHANGE_TYPES = [
    "Vocabulary simplification",
    "Sentence restructuring",
    "Repetitive wording reduction",
    "Formality reduction",
    "Clarity improvement",
    "Sentence variation",
    "Filler removal",
    "Transition improvement",
    "Grammar improvement",
    "Readability improvement",
]

_FENCE = re.compile(r"^\s*```(?:json|JSON)?\s*|\s*```\s*$")


# ---------------------------------------------------------------------------
# JSON recovery
# ---------------------------------------------------------------------------
def extract_json(raw: str) -> dict:
    """Pull a JSON object out of a model reply, repairing common mistakes."""
    if not raw or not raw.strip():
        raise ModelResponseError("The model returned an empty response.")

    text = _FENCE.sub("", raw.strip()).strip()

    candidate = _first_balanced_object(text)
    if candidate is None:
        raise ModelResponseError(
            "The model response contained no JSON object.",
            f"First 200 characters: {text[:200]}",
        )

    for attempt in (candidate, _repair(candidate)):
        try:
            parsed = json.loads(attempt)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue

    raise ModelResponseError(
        "The model returned malformed JSON that could not be repaired.",
        f"First 200 characters: {candidate[:200]}",
    )


def _first_balanced_object(text: str) -> str | None:
    """Return the first `{...}` block, respecting strings and escapes."""
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for position in range(start, len(text)):
        char = text[position]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:position + 1]
    # Unterminated object: hand back what we have so the repairer can close it.
    return text[start:]


def _repair(candidate: str) -> str:
    """Best-effort fixes for the mistakes models actually make."""
    fixed = candidate
    fixed = fixed.replace("\u201c", '"').replace("\u201d", '"')
    fixed = fixed.replace("\u2018", "'").replace("\u2019", "'")
    fixed = re.sub(r",\s*([}\]])", r"\1", fixed)          # trailing commas
    fixed = re.sub(r"//[^\n\"]*", "", fixed)               # line comments
    # Close any objects/arrays the model forgot to close.
    opens = fixed.count("{") - fixed.count("}")
    if opens > 0:
        fixed += "}" * opens
    opens = fixed.count("[") - fixed.count("]")
    if opens > 0:
        fixed += "]" * opens
    return fixed


# ---------------------------------------------------------------------------
# Small coercion helpers
# ---------------------------------------------------------------------------
def _as_text(value, default: str = "") -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return default
    return str(value).strip()


def _pick(value, allowed: list[str], default: str) -> str:
    """Map a free-form label onto one of the allowed labels."""
    text = _as_text(value).lower()
    if not text:
        return default
    for option in allowed:
        if option.lower() == text:
            return option
    for option in allowed:
        if option.lower().split()[0] in text:
            return option
    return default


def _as_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------
def validate_analysis(payload: dict) -> dict:
    """Coerce a raw analysis payload into the engine's fixed schema."""
    if not isinstance(payload, dict):
        raise ModelResponseError("The analysis response was not a JSON object.")

    assessment = _as_text(payload.get("overall_assessment"))
    likelihood = _pick(payload.get("ai_likelihood"), LIKELIHOOD_VALUES, "Inconclusive")
    if not assessment and likelihood == "Inconclusive":
        raise ModelResponseError(
            "The analysis response contained none of the required fields."
        )

    indicators = []
    for item in _as_list(payload.get("indicators")):
        if not isinstance(item, dict):
            continue
        explanation = _as_text(item.get("explanation"))
        label = _as_text(item.get("type"))
        if not (explanation or label):
            continue
        indicators.append(
            {
                "type": label or "Unlabelled pattern",
                "severity": _pick(item.get("severity"), LEVELS, "Low"),
                "explanation": explanation or "No explanation supplied by the model.",
            }
        )

    flagged = []
    for item in _as_list(payload.get("flagged_passages")):
        if not isinstance(item, dict):
            continue
        original = _as_text(item.get("original"))
        if not original:
            continue
        flagged.append(
            {
                "original": original,
                "reason": _as_text(item.get("reason"), "No reason supplied."),
                "indicator_type": _as_text(item.get("indicator_type"), "Unspecified"),
                "strength": _pick(item.get("strength"), LEVELS, "Low"),
            }
        )

    return {
        "overall_assessment": assessment or "No summary supplied by the model.",
        "ai_likelihood": likelihood,
        "confidence": _pick(payload.get("confidence"), LEVELS, "Low"),
        "readability": _as_text(payload.get("readability"), "Not assessed."),
        "indicators": indicators,
        "flagged_passages": flagged,
    }


def validate_rewrite(payload: dict) -> dict:
    """Coerce a raw rewrite payload into the engine's fixed schema."""
    if not isinstance(payload, dict):
        raise ModelResponseError("The rewrite response was not a JSON object.")

    rewritten = _as_text(payload.get("rewritten"))
    if not rewritten:
        raise ModelResponseError(
            "The rewrite response did not contain any rewritten text."
        )

    changes = []
    for item in _as_list(payload.get("changes")):
        if not isinstance(item, dict):
            continue
        original = _as_text(item.get("original"))
        new_text = _as_text(item.get("rewritten"))
        if not original and not new_text:
            continue
        changes.append(
            {
                "original": original,
                "rewritten": new_text,
                "change_type": _pick(
                    item.get("change_type"), CHANGE_TYPES, "Readability improvement"
                ),
                "reason": _as_text(item.get("reason"), "No reason supplied."),
            }
        )

    return {
        "rewritten": rewritten,
        "changes": changes,
        "preservation_notes": _as_text(payload.get("preservation_notes"), ""),
    }
