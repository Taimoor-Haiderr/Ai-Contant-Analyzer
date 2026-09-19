"""
Change reporting.

Turns the raw edit list returned by the rewriter into a transparent report:
what changed, what kind of change it was, why, and how the totals break down.

The engine never reports a bare "humanized successfully" - every summary is
backed by the individual transformations listed underneath it.
"""

from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher

# Change types that usually alter structure rather than a single word.
MAJOR_TYPES = {
    "Sentence restructuring",
    "Sentence variation",
    "Repetitive wording reduction",
    "Clarity improvement",
}


def _similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def classify_change(change: dict) -> str:
    """Decide whether an individual edit is major or minor."""
    original = change.get("original", "")
    rewritten = change.get("rewritten", "")
    similarity = _similarity(original, rewritten)
    length_delta = abs(len(original.split()) - len(rewritten.split()))

    if change.get("change_type") in MAJOR_TYPES:
        return "major"
    if similarity < 0.6 or length_delta >= 4:
        return "major"
    return "minor"


def build_change_report(rewrite_result: dict, max_examples: int = 10) -> dict:
    """
    Build the full change report from a `rewrite_content(...)` result.

    Returns counts, a per-type breakdown, every recorded change and a small set
    of before/after examples for display.
    """
    raw_changes = rewrite_result.get("raw_changes", []) or []
    preservation = rewrite_result.get("preservation", {}) or {}

    changes = []
    for item in raw_changes:
        entry = {
            "original": item.get("original", ""),
            "rewritten": item.get("rewritten", ""),
            "change_type": item.get("change_type", "Readability improvement"),
            "reason": item.get("reason", ""),
        }
        entry["scale"] = classify_change(entry)
        changes.append(entry)

    by_type = Counter(c["change_type"] for c in changes)
    major = sum(1 for c in changes if c["scale"] == "major")
    minor = len(changes) - major

    missing = preservation.get("missing_tokens") or {}
    if missing:
        meaning_status = (
            "Needs review - the rewrite is missing some numbers, dates, URLs or "
            "citations that appeared in the original."
        )
    elif not changes:
        meaning_status = "Unchanged - the model reported no edits."
    else:
        meaning_status = (
            "Preserved - the rewrite keeps the original numbers, dates, URLs and "
            "citations, and stays within a normal length range."
        )

    examples = [
        {
            "original": c["original"],
            "rewritten": c["rewritten"],
            "change_type": c["change_type"],
            "reason": c["reason"],
        }
        for c in changes
        if c["original"] and c["rewritten"]
    ][:max_examples]

    return {
        "summary": {
            "total_changes": len(changes),
            "major_changes": major,
            "minor_changes": minor,
            "changes_by_type": dict(by_type.most_common()),
            "meaning_preservation_status": meaning_status,
            "facts_preserved_status": preservation.get(
                "facts_preserved_status", "Not verified"
            ),
            "original_word_count": preservation.get("original_word_count", 0),
            "rewritten_word_count": preservation.get("rewritten_word_count", 0),
            "length_ratio": preservation.get("length_ratio", 0.0),
            "verification_notes": preservation.get("notes", []),
            "model_preservation_notes": rewrite_result.get(
                "model_preservation_notes", ""
            ),
        },
        "changes": changes,
        "examples": examples,
    }


def build_before_after(rewrite_result: dict, analysis: dict | None = None) -> dict:
    """
    Assemble the Feature 6 structure: original, rewritten, changes, analysis.

    This is the object a future frontend renders side by side.
    """
    change_report = build_change_report(rewrite_result)
    return {
        "ok": True,
        "source": rewrite_result.get("source", "text input"),
        "generated_at": rewrite_result.get("generated_at"),
        "mode": rewrite_result.get("mode"),
        "original_content": rewrite_result.get("original", ""),
        "rewritten_content": rewrite_result.get("rewritten", ""),
        "changes": change_report,
        "analysis": analysis,
    }
