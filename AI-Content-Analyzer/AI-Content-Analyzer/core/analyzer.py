"""
Content analysis.

Two independent layers:

1. `compute_statistics()` - deterministic, offline, reproducible numbers about
   the text (counts, sentence-length spread, vocabulary diversity, readability,
   repeated phrases).  These never depend on a model.
2. `analyze_content()`    - the model's qualitative read of each chunk, merged
   back into one report.

The output deliberately uses labels ("Low / Moderate / High indication",
"Inconclusive") instead of a fabricated accuracy percentage.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

from config import DISCLAIMER, Settings, get_settings
from core.ai_provider import TASK_ANALYSIS, AIProvider, get_provider
from core.chunker import chunk_text, split_paragraphs, split_sentences
from core.errors import AppError, EmptyContentError, ModelResponseError
from core.prompts import ANALYSIS_SYSTEM, ANALYSIS_USER
from core.validator import extract_json, validate_analysis

_LIKELIHOOD_SCORE = {
    "Low indication": 1.0,
    "Moderate indication": 2.0,
    "High indication": 3.0,
}
_SCORE_LIKELIHOOD = [
    (1.5, "Low indication"),
    (2.5, "Moderate indication"),
    (99.0, "High indication"),
]
_LEVEL_SCORE = {"Low": 1.0, "Moderate": 2.0, "High": 3.0}
_SCORE_LEVEL = [(1.5, "Low"), (2.5, "Moderate"), (99.0, "High")]

_VOWEL_GROUPS = re.compile(r"[aeiouy]+")
_WORD = re.compile(r"[A-Za-z']+")


# ---------------------------------------------------------------------------
# Deterministic statistics
# ---------------------------------------------------------------------------
def _count_syllables(word: str) -> int:
    word = word.lower().strip("'")
    if not word:
        return 0
    groups = _VOWEL_GROUPS.findall(word)
    count = len(groups)
    if word.endswith("e") and count > 1 and not word.endswith(("le", "ee")):
        count -= 1
    return max(1, count)


def _readability_label(score: float) -> str:
    if score >= 80:
        return "Very easy"
    if score >= 70:
        return "Easy"
    if score >= 60:
        return "Standard"
    if score >= 50:
        return "Fairly difficult"
    if score >= 30:
        return "Difficult"
    return "Very difficult"


def compute_statistics(text: str) -> dict:
    """Offline descriptive statistics for a piece of text."""
    paragraphs = split_paragraphs(text)
    sentences = [s for s in split_sentences(text.replace("\n", " ")) if s.strip()]
    words = _WORD.findall(text)
    word_count = len(words)

    lengths = [len(_WORD.findall(s)) for s in sentences] or [0]
    mean_length = sum(lengths) / len(lengths)
    variance = sum((n - mean_length) ** 2 for n in lengths) / len(lengths)
    deviation = variance ** 0.5

    unique = {w.lower() for w in words}
    diversity = len(unique) / word_count if word_count else 0.0

    syllables = sum(_count_syllables(w) for w in words)
    if word_count and sentences:
        flesch = (
            206.835
            - 1.015 * (word_count / len(sentences))
            - 84.6 * (syllables / word_count)
        )
    else:
        flesch = 0.0
    flesch = round(max(-50.0, min(120.0, flesch)), 1)

    # Repeated 3-word phrases (a simple, honest repetition signal).
    lowered = [w.lower() for w in words]
    trigrams = Counter(
        " ".join(lowered[i:i + 3]) for i in range(max(0, len(lowered) - 2))
    )
    repeated = [
        {"phrase": phrase, "occurrences": count}
        for phrase, count in trigrams.most_common(10)
        if count >= 3
    ]

    return {
        "character_count": len(text),
        "word_count": word_count,
        "unique_word_count": len(unique),
        "sentence_count": len(sentences),
        "paragraph_count": len(paragraphs),
        "average_sentence_length_words": round(mean_length, 2),
        "sentence_length_standard_deviation": round(deviation, 2),
        "sentence_length_variation_ratio": (
            round(deviation / mean_length, 3) if mean_length else 0.0
        ),
        "vocabulary_diversity_ratio": round(diversity, 3),
        "flesch_reading_ease": flesch,
        "readability_label": _readability_label(flesch),
        "repeated_phrases": repeated,
    }


# ---------------------------------------------------------------------------
# Merging chunk results
# ---------------------------------------------------------------------------
def _weighted_label(pairs: list[tuple[str, int]], table: dict, ladder: list) -> str:
    """Average labels weighted by chunk size, ignoring 'Inconclusive'."""
    usable = [(table[label], weight) for label, weight in pairs if label in table]
    if not usable:
        return "Inconclusive"
    total_weight = sum(max(1, w) for _, w in usable)
    score = sum(value * max(1, w) for value, w in usable) / total_weight
    for threshold, label in ladder:
        if score < threshold:
            return label
    return ladder[-1][1]


def _merge_indicators(all_indicators: list[dict]) -> list[dict]:
    """Collapse duplicate indicator types, keeping the strongest severity."""
    merged: dict[str, dict] = {}
    for item in all_indicators:
        key = item["type"].strip().lower()
        existing = merged.get(key)
        if existing is None:
            merged[key] = dict(item, occurrences=1)
            continue
        existing["occurrences"] += 1
        if _LEVEL_SCORE.get(item["severity"], 0) > _LEVEL_SCORE.get(
            existing["severity"], 0
        ):
            existing["severity"] = item["severity"]
            existing["explanation"] = item["explanation"]
    ordered = sorted(
        merged.values(),
        key=lambda i: (-_LEVEL_SCORE.get(i["severity"], 0), -i["occurrences"]),
    )
    return ordered


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def analyze_content(
    text: str,
    settings: Settings | None = None,
    provider: AIProvider | None = None,
    source_label: str = "text input",
) -> dict:
    """
    Analyse `text` and return the structured analysis report.

    Raises AppError subclasses on failure; never returns a fabricated result.
    """
    settings = settings or get_settings()
    if not text or not text.strip():
        raise EmptyContentError(
            "There is no text to analyse.",
            "The input was empty or contained only whitespace.",
        )

    provider = provider or get_provider(settings)
    statistics = compute_statistics(text)
    chunks = chunk_text(text, settings.max_chunk_chars)

    chunk_reports: list[dict] = []
    failures: list[dict] = []

    for chunk in chunks:
        prompt = ANALYSIS_USER.format(text=chunk.text)
        try:
            raw = provider.complete(ANALYSIS_SYSTEM, prompt, TASK_ANALYSIS)
            report = validate_analysis(extract_json(raw))
        except ModelResponseError:
            # One controlled retry with a firmer instruction.
            try:
                raw = provider.complete(
                    ANALYSIS_SYSTEM
                    + "\nYour previous reply was not valid JSON. Reply with JSON only.",
                    prompt,
                    TASK_ANALYSIS,
                )
                report = validate_analysis(extract_json(raw))
            except AppError as retry_exc:
                failures.append(
                    {"chunk": chunk.index, "error": retry_exc.to_dict()["error"]}
                )
                continue
        except AppError as exc:
            failures.append({"chunk": chunk.index, "error": exc.to_dict()["error"]})
            continue

        report["_chunk_index"] = chunk.index
        report["_word_count"] = chunk.word_count
        chunk_reports.append(report)

    if not chunk_reports:
        detail = failures[0]["error"]["message"] if failures else "Unknown cause."
        raise ModelResponseError(
            "The analysis could not be completed: every chunk failed.", detail
        )

    likelihood = _weighted_label(
        [(r["ai_likelihood"], r["_word_count"]) for r in chunk_reports],
        _LIKELIHOOD_SCORE,
        _SCORE_LIKELIHOOD,
    )
    confidence = _weighted_label(
        [(r["confidence"], r["_word_count"]) for r in chunk_reports],
        _LEVEL_SCORE,
        _SCORE_LEVEL,
    )

    # Short samples are never presented as a confident verdict.
    if statistics["word_count"] < 80:
        likelihood = "Inconclusive"
        confidence = "Low"

    if failures:
        confidence = "Low"

    indicators = _merge_indicators(
        [item for report in chunk_reports for item in report["indicators"]]
    )
    flagged = [
        dict(passage, chunk=report["_chunk_index"])
        for report in chunk_reports
        for passage in report["flagged_passages"]
    ]

    summaries = [r["overall_assessment"] for r in chunk_reports if r["overall_assessment"]]
    overall = summaries[0] if len(summaries) == 1 else " ".join(summaries[:3])

    return {
        "ok": True,
        "source": source_label,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "mock" if provider.is_mock else "model",
        "model": "offline-mock" if provider.is_mock else (settings.model_name or "unset"),
        "overall_assessment": overall,
        "ai_likelihood": likelihood,
        "confidence": confidence,
        "readability": statistics["readability_label"],
        "statistics": statistics,
        "indicators": indicators,
        "flagged_passages": flagged,
        "chunks_processed": len(chunk_reports),
        "chunks_total": len(chunks),
        "chunk_failures": failures,
        "limitations": DISCLAIMER,
    }
