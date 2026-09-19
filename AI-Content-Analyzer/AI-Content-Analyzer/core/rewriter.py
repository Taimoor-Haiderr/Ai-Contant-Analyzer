"""
Natural rewriting.

The rewriter sends each chunk to the model with strict preservation rules, then
verifies the result locally:

  * numbers, dates, URLs and citation markers present in the source must still
    be present in the rewrite;
  * paragraph count must match;
  * length must stay within a sane band (no silent truncation, no padding).

Findings are reported honestly rather than hidden.  The original text object is
never modified - a rewrite always produces a new string.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from config import Settings, get_settings
from core.ai_provider import TASK_REWRITE, AIProvider, get_provider
from core.chunker import chunk_text, join_chunks, split_paragraphs
from core.errors import AppError, EmptyContentError, ModelResponseError
from core.prompts import REWRITE_SYSTEM, REWRITE_USER
from core.validator import extract_json, validate_rewrite

_NUMBER = re.compile(r"\b\d[\d,.:/-]*\b")
_URL = re.compile(r"https?://\S+|www\.\S+")
_CITATION = re.compile(r"\[[0-9]{1,3}\]|\([A-Z][A-Za-z'\-]+(?: et al\.)?,? \d{4}\)")
_MONTH = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\b",
    re.IGNORECASE,
)


def _tokens_to_preserve(text: str) -> dict[str, list[str]]:
    """Collect the items the rewrite is not allowed to lose."""
    return {
        "numbers": sorted(set(_NUMBER.findall(text))),
        "urls": sorted(set(_URL.findall(text))),
        "citations": sorted(set(_CITATION.findall(text))),
        "months": sorted({m.capitalize() for m in _MONTH.findall(text)}),
    }


def verify_preservation(original: str, rewritten: str) -> dict:
    """Compare original and rewritten text for dropped facts."""
    before = _tokens_to_preserve(original)
    after = _tokens_to_preserve(rewritten)

    missing: dict[str, list[str]] = {}
    for key, values in before.items():
        lost = [v for v in values if v not in after[key]]
        if lost:
            missing[key] = lost

    original_words = len(original.split())
    rewritten_words = len(rewritten.split())
    ratio = (rewritten_words / original_words) if original_words else 0.0

    paragraphs_before = len(split_paragraphs(original))
    paragraphs_after = len(split_paragraphs(rewritten))

    notes: list[str] = []
    if missing:
        for key, values in missing.items():
            notes.append(
                f"{len(values)} {key} from the original were not found in the rewrite: "
                + ", ".join(values[:5])
                + ("..." if len(values) > 5 else "")
            )
    if paragraphs_before != paragraphs_after:
        notes.append(
            f"Paragraph count changed from {paragraphs_before} to {paragraphs_after}."
        )
    if ratio and (ratio < 0.6 or ratio > 1.6):
        notes.append(
            f"Length changed noticeably ({original_words} -> {rewritten_words} words)."
        )

    if not notes:
        status = "Verified - no dropped numbers, dates, URLs or citations detected"
    elif missing:
        status = "Needs review - some factual tokens were not found in the rewrite"
    else:
        status = "Mostly preserved - structural differences noted"

    return {
        "facts_preserved_status": status,
        "missing_tokens": missing,
        "original_word_count": original_words,
        "rewritten_word_count": rewritten_words,
        "length_ratio": round(ratio, 3),
        "paragraphs_before": paragraphs_before,
        "paragraphs_after": paragraphs_after,
        "notes": notes,
    }


def rewrite_content(
    text: str,
    settings: Settings | None = None,
    provider: AIProvider | None = None,
    source_label: str = "text input",
) -> dict:
    """
    Rewrite `text` naturally and return the result plus raw change entries.

    The returned dict is consumed by `core.change_report.build_change_report`.
    """
    settings = settings or get_settings()
    if not text or not text.strip():
        raise EmptyContentError(
            "There is no text to rewrite.",
            "The input was empty or contained only whitespace.",
        )

    provider = provider or get_provider(settings)
    chunks = chunk_text(text, settings.max_chunk_chars)

    pieces: list[tuple[str, bool]] = []
    changes: list[dict] = []
    preservation_notes: list[str] = []
    failures: list[dict] = []

    for chunk in chunks:
        prompt = REWRITE_USER.format(
            text=chunk.text, paragraph_count=chunk.paragraph_count
        )
        result = None
        try:
            raw = provider.complete(REWRITE_SYSTEM, prompt, TASK_REWRITE)
            result = validate_rewrite(extract_json(raw))
        except ModelResponseError:
            try:
                raw = provider.complete(
                    REWRITE_SYSTEM
                    + "\nYour previous reply was not valid JSON. Reply with JSON only.",
                    prompt,
                    TASK_REWRITE,
                )
                result = validate_rewrite(extract_json(raw))
            except AppError as retry_exc:
                failures.append(
                    {"chunk": chunk.index, "error": retry_exc.to_dict()["error"]}
                )
        except AppError as exc:
            failures.append({"chunk": chunk.index, "error": exc.to_dict()["error"]})

        if result is None:
            # Keep the original wording for this chunk rather than losing content.
            pieces.append((chunk.text, chunk.starts_new_paragraph))
            continue

        pieces.append((result["rewritten"], chunk.starts_new_paragraph))
        changes.extend(result["changes"])
        if result["preservation_notes"]:
            preservation_notes.append(result["preservation_notes"])

    if failures and len(failures) == len(chunks):
        raise ModelResponseError(
            "The rewrite could not be completed: every chunk failed.",
            failures[0]["error"]["message"],
        )

    rewritten = join_chunks(pieces)
    preservation = verify_preservation(text, rewritten)

    return {
        "ok": True,
        "source": source_label,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "mock" if provider.is_mock else "model",
        "model": "offline-mock" if provider.is_mock else (settings.model_name or "unset"),
        "original": text,          # the original is carried through untouched
        "rewritten": rewritten,
        "raw_changes": changes,
        "preservation": preservation,
        "model_preservation_notes": " ".join(preservation_notes),
        "chunks_total": len(chunks),
        "chunks_rewritten": len(chunks) - len(failures),
        "chunk_failures": failures,
    }
