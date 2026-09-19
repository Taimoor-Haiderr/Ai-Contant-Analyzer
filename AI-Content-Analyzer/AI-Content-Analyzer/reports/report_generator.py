"""
Report generation.

`build_report(...)` assembles one dictionary containing everything the project
promises to report.  The renderers below turn that same dictionary into JSON,
plain text, HTML or PDF, so every format always shows the same facts.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from config import DISCLAIMER

SECTION_LINE = "=" * 72
THIN_LINE = "-" * 72


def build_report(
    *,
    source_label: str,
    input_type: str,
    analysis: dict | None = None,
    rewrite: dict | None = None,
    change_report: dict | None = None,
    extraction_metadata: dict | None = None,
    warnings: list[str] | None = None,
) -> dict:
    """Combine the pipeline outputs into one machine-readable report."""
    statistics = (analysis or {}).get("statistics", {})
    return {
        "report_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "name": source_label,
            "input_type": input_type,
            "metadata": extraction_metadata or {},
        },
        "mode": (analysis or rewrite or {}).get("mode", "unknown"),
        "model": (analysis or rewrite or {}).get("model", "unknown"),
        "statistics": statistics,
        "analysis": (
            {
                "overall_assessment": analysis.get("overall_assessment", ""),
                "ai_likelihood": analysis.get("ai_likelihood", "Inconclusive"),
                "confidence": analysis.get("confidence", "Low"),
                "readability": analysis.get("readability", ""),
                "indicators": analysis.get("indicators", []),
                "flagged_passages": analysis.get("flagged_passages", []),
                "chunks_processed": analysis.get("chunks_processed", 0),
                "chunks_total": analysis.get("chunks_total", 0),
                "chunk_failures": analysis.get("chunk_failures", []),
            }
            if analysis
            else None
        ),
        "rewrite": (
            {
                "original_content": rewrite.get("original", ""),
                "rewritten_content": rewrite.get("rewritten", ""),
                "preservation": rewrite.get("preservation", {}),
                "chunks_total": rewrite.get("chunks_total", 0),
                "chunks_rewritten": rewrite.get("chunks_rewritten", 0),
                "chunk_failures": rewrite.get("chunk_failures", []),
            }
            if rewrite
            else None
        ),
        "changes": change_report,
        "warnings": warnings or [],
        "limitations": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Plain text rendering
# ---------------------------------------------------------------------------
def render_txt(report: dict) -> str:
    """Render the report as a readable plain-text document."""
    lines: list[str] = []
    add = lines.append

    add(SECTION_LINE)
    add("AI CONTENT ANALYZER & NATURAL REWRITER - REPORT")
    add(SECTION_LINE)
    add(f"Source        : {report['source']['name']}")
    add(f"Input type    : {report['source']['input_type']}")
    add(f"Generated     : {report['generated_at']}")
    add(f"Mode          : {report['mode']} (model: {report['model']})")
    if report["mode"] == "mock":
        add("NOTE          : Offline test mode - results come from local heuristics,")
        add("                not from a language model.")
    add("")

    statistics = report.get("statistics") or {}
    if statistics:
        add("1. CONTENT STATISTICS")
        add(THIN_LINE)
        add(f"Words                     : {statistics.get('word_count', 0)}")
        add(f"Unique words              : {statistics.get('unique_word_count', 0)}")
        add(f"Sentences                 : {statistics.get('sentence_count', 0)}")
        add(f"Paragraphs                : {statistics.get('paragraph_count', 0)}")
        add("Avg sentence length       : "
            f"{statistics.get('average_sentence_length_words', 0)} words")
        add("Sentence length std dev   : "
            f"{statistics.get('sentence_length_standard_deviation', 0)}")
        add("Length variation ratio    : "
            f"{statistics.get('sentence_length_variation_ratio', 0)}")
        add("Vocabulary diversity      : "
            f"{statistics.get('vocabulary_diversity_ratio', 0)}")
        add(f"Flesch reading ease       : {statistics.get('flesch_reading_ease', 0)} "
            f"({statistics.get('readability_label', 'n/a')})")
        repeated = statistics.get("repeated_phrases") or []
        if repeated:
            add("Repeated 3-word phrases   :")
            for item in repeated[:5]:
                add(f"  - \"{item['phrase']}\" x{item['occurrences']}")
        add("")

    analysis = report.get("analysis")
    if analysis:
        add("2. AI-CONTENT INDICATORS")
        add(THIN_LINE)
        add(f"Indication level : {analysis['ai_likelihood']}")
        add(f"Confidence       : {analysis['confidence']}")
        add(f"Readability      : {analysis['readability']}")
        add(f"Chunks analysed  : {analysis['chunks_processed']}/{analysis['chunks_total']}")
        add("")
        add("Assessment:")
        add(_wrap(analysis["overall_assessment"]))
        add("")

        if analysis["indicators"]:
            add("3. LINGUISTIC OBSERVATIONS")
            add(THIN_LINE)
            for index, indicator in enumerate(analysis["indicators"], start=1):
                add(f"{index}. [{indicator['severity']}] {indicator['type']}")
                add(_wrap(indicator["explanation"], indent="   "))
            add("")

        if analysis["flagged_passages"]:
            add("4. FLAGGED PASSAGES")
            add(THIN_LINE)
            for index, passage in enumerate(analysis["flagged_passages"], start=1):
                add(f"{index}. Strength: {passage['strength']} | "
                    f"Type: {passage['indicator_type']}")
                add(_wrap(f"ORIGINAL: {passage['original']}", indent="   "))
                add(_wrap(f"REASON  : {passage['reason']}", indent="   "))
                add("")

        if analysis["chunk_failures"]:
            add(f"NOTE: {len(analysis['chunk_failures'])} chunk(s) failed to analyse.")
            add("")

    changes = report.get("changes")
    if changes:
        summary = changes["summary"]
        add("5. NATURAL REWRITE SUMMARY")
        add(THIN_LINE)
        add(f"Total changes        : {summary['total_changes']}")
        add(f"Major changes        : {summary['major_changes']}")
        add(f"Minor changes        : {summary['minor_changes']}")
        add(f"Words before/after   : {summary['original_word_count']} -> "
            f"{summary['rewritten_word_count']} (ratio {summary['length_ratio']})")
        add(f"Meaning preservation : {summary['meaning_preservation_status']}")
        add(f"Facts preserved      : {summary['facts_preserved_status']}")
        if summary["changes_by_type"]:
            add("Changes by type:")
            for change_type, count in summary["changes_by_type"].items():
                add(f"  - {change_type}: {count}")
        for note in summary.get("verification_notes", []):
            add(f"  ! {note}")
        add("")

        if changes["examples"]:
            add("6. BEFORE / AFTER EXAMPLES")
            add(THIN_LINE)
            for index, example in enumerate(changes["examples"], start=1):
                add(f"{index}. {example['change_type']}")
                add(_wrap(f"BEFORE: {example['original']}", indent="   "))
                add(_wrap(f"AFTER : {example['rewritten']}", indent="   "))
                add(_wrap(f"WHY   : {example['reason']}", indent="   "))
                add("")

    if report.get("warnings"):
        add("7. WARNINGS")
        add(THIN_LINE)
        for warning in report["warnings"]:
            add(f"  - {warning}")
        add("")

    add("8. LIMITATIONS")
    add(THIN_LINE)
    add(_wrap(report["limitations"]))
    add("")
    add(SECTION_LINE)
    return "\n".join(lines)


def _wrap(text: str, width: int = 72, indent: str = "") -> str:
    """Simple word wrapper used by the text report."""
    words = (text or "").split()
    if not words:
        return indent
    lines: list[str] = []
    current = indent
    for word in words:
        if len(current) + len(word) + 1 > width and current.strip():
            lines.append(current.rstrip())
            current = indent + word
        else:
            current = f"{current} {word}" if current.strip() else indent + word
    lines.append(current.rstrip())
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------
def render_html(report: dict) -> str:
    """Render the report as a standalone, dependency-free HTML page."""
    esc = html.escape
    statistics = report.get("statistics") or {}
    analysis = report.get("analysis")
    changes = report.get("changes")

    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>Analysis report - {esc(report['source']['name'])}</title>",
        "<style>",
        ":root{color-scheme:dark light}",
        "body{margin:0;padding:2rem;background:#0f1115;color:#e6e8eb;"
        "font-family:ui-sans-serif,system-ui,'Segoe UI',Roboto,sans-serif;line-height:1.6}",
        ".wrap{max-width:900px;margin:0 auto}",
        "h1{font-size:1.5rem;margin:0 0 .25rem}",
        "h2{font-size:1.1rem;margin:2rem 0 .5rem;border-bottom:1px solid #2a2f3a;"
        "padding-bottom:.35rem}",
        ".meta{color:#9aa4b2;font-size:.9rem}",
        ".grid{display:grid;gap:.75rem;margin:1rem 0;"
        "grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}",
        ".card{background:#171a21;border:1px solid #242936;border-radius:10px;padding:.75rem 1rem}",
        ".card .k{color:#9aa4b2;font-size:.78rem;text-transform:uppercase;letter-spacing:.04em}",
        ".card .v{font-size:1.15rem;font-weight:600}",
        ".badge{display:inline-block;padding:.15rem .6rem;border-radius:999px;font-size:.8rem;"
        "border:1px solid #3a4152;background:#1d2029}",
        ".item{background:#171a21;border:1px solid #242936;border-radius:10px;"
        "padding:.75rem 1rem;margin:.6rem 0}",
        ".sev-High{border-left:4px solid #e0574a}.sev-Moderate{border-left:4px solid #e0a23c}",
        ".sev-Low{border-left:4px solid #4a9de0}",
        "blockquote{margin:.4rem 0;padding:.5rem .8rem;background:#12151b;"
        "border-left:3px solid #3a4152;white-space:pre-wrap}",
        ".ba{display:grid;grid-template-columns:1fr 1fr;gap:.6rem}",
        "@media(max-width:700px){.ba{grid-template-columns:1fr}}",
        ".disclaimer{background:#1b1710;border:1px solid #4a3b1d;border-radius:10px;"
        "padding:1rem;margin-top:2rem;color:#e8d9b5;font-size:.92rem}",
        "table{width:100%;border-collapse:collapse;font-size:.92rem}",
        "td,th{border-bottom:1px solid #242936;padding:.4rem .5rem;"
        "text-align:left;vertical-align:top}",
        "</style></head><body><div class='wrap'>",
        "<h1>AI Content Analysis Report</h1>",
        f"<p class='meta'>{esc(report['source']['name'])} &middot; "
        f"{esc(str(report['source']['input_type']))} &middot; "
        f"{esc(report['generated_at'])} &middot; "
        f"mode: {esc(str(report['mode']))}</p>",
    ]

    if report["mode"] == "mock":
        parts.append(
            "<p class='badge'>Offline test mode - local heuristics, not a language model</p>"
        )

    if statistics:
        parts.append("<h2>Content statistics</h2><div class='grid'>")
        for key, label in [
            ("word_count", "Words"),
            ("sentence_count", "Sentences"),
            ("paragraph_count", "Paragraphs"),
            ("average_sentence_length_words", "Avg sentence"),
            ("sentence_length_variation_ratio", "Length variation"),
            ("vocabulary_diversity_ratio", "Vocab diversity"),
            ("flesch_reading_ease", "Reading ease"),
        ]:
            parts.append(
                f"<div class='card'><div class='k'>{label}</div>"
                f"<div class='v'>{esc(str(statistics.get(key, '-')))}</div></div>"
            )
        parts.append("</div>")

    if analysis:
        parts.append("<h2>AI-content indicators</h2>")
        parts.append(
            f"<p><span class='badge'>Indication: {esc(analysis['ai_likelihood'])}</span> "
            f"<span class='badge'>Confidence: {esc(analysis['confidence'])}</span> "
            f"<span class='badge'>Readability: {esc(analysis['readability'])}</span></p>"
        )
        parts.append(f"<p>{esc(analysis['overall_assessment'])}</p>")

        if analysis["indicators"]:
            parts.append("<h2>Linguistic observations</h2>")
            for indicator in analysis["indicators"]:
                parts.append(
                    f"<div class='item sev-{esc(indicator['severity'])}'>"
                    f"<strong>{esc(indicator['type'])}</strong> "
                    f"<span class='badge'>{esc(indicator['severity'])}</span>"
                    f"<p>{esc(indicator['explanation'])}</p></div>"
                )

        if analysis["flagged_passages"]:
            parts.append("<h2>Flagged passages</h2>")
            for passage in analysis["flagged_passages"]:
                parts.append(
                    f"<div class='item sev-{esc(passage['strength'])}'>"
                    f"<span class='badge'>{esc(passage['indicator_type'])}</span> "
                    f"<span class='badge'>{esc(passage['strength'])}</span>"
                    f"<blockquote>{esc(passage['original'])}</blockquote>"
                    f"<p>{esc(passage['reason'])}</p></div>"
                )

    if changes:
        summary = changes["summary"]
        parts.append("<h2>Natural rewrite summary</h2><div class='grid'>")
        for key, label in [
            ("total_changes", "Total changes"),
            ("major_changes", "Major"),
            ("minor_changes", "Minor"),
            ("original_word_count", "Words before"),
            ("rewritten_word_count", "Words after"),
        ]:
            parts.append(
                f"<div class='card'><div class='k'>{label}</div>"
                f"<div class='v'>{esc(str(summary.get(key, '-')))}</div></div>"
            )
        parts.append("</div>")
        parts.append(
            f"<p><strong>Meaning:</strong> {esc(summary['meaning_preservation_status'])}<br>"
            f"<strong>Facts:</strong> {esc(summary['facts_preserved_status'])}</p>"
        )

        if summary["changes_by_type"]:
            parts.append("<table><tr><th>Change type</th><th>Count</th></tr>")
            for change_type, count in summary["changes_by_type"].items():
                parts.append(f"<tr><td>{esc(change_type)}</td><td>{count}</td></tr>")
            parts.append("</table>")

        if changes["examples"]:
            parts.append("<h2>Before / after</h2>")
            for example in changes["examples"]:
                parts.append(
                    "<div class='item'>"
                    f"<span class='badge'>{esc(example['change_type'])}</span>"
                    "<div class='ba'>"
                    f"<blockquote>{esc(example['original'])}</blockquote>"
                    f"<blockquote>{esc(example['rewritten'])}</blockquote>"
                    "</div>"
                    f"<p class='meta'>{esc(example['reason'])}</p></div>"
                )

    if report.get("warnings"):
        parts.append("<h2>Warnings</h2><ul>")
        for warning in report["warnings"]:
            parts.append(f"<li>{esc(warning)}</li>")
        parts.append("</ul>")

    parts.append(
        f"<div class='disclaimer'><strong>Limitations.</strong> {esc(report['limitations'])}</div>"
    )
    parts.append("</div></body></html>")
    return "\n".join(parts)


def render_json(report: dict) -> str:
    """Pretty-printed JSON version of the report."""
    return json.dumps(report, indent=2, ensure_ascii=False)


def write_report(
    report: dict,
    destination: Path,
    fmt: str = "txt",
) -> Path:
    """Write a rendered report to `destination`. Formats: json, txt, html."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    renderers = {"json": render_json, "txt": render_txt, "html": render_html}
    renderer = renderers.get(fmt.lower())
    if renderer is None:
        raise ValueError(f"Unknown report format '{fmt}'. Use json, txt or html.")
    destination.write_text(renderer(report), encoding="utf-8")
    return destination
