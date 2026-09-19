"""
Public engine API.

This module is the ONLY thing a future frontend needs to import.  Every
function takes plain arguments, returns a plain JSON-serialisable dict, and
never raises on expected failures - errors come back as
`{"ok": False, "error": {...}}`.

    analyze_text / rewrite_text
    analyze_pdf  / rewrite_pdf
    analyze_docx / rewrite_docx
    analyze_csv  / rewrite_csv
    analyze_xlsx / rewrite_xlsx
    analyze_file / rewrite_file      (dispatch by extension)
    generate_change_report
    generate_report
    export_result

Business logic lives in `core/`, `processors/`, `reports/` and `exports/`;
nothing here knows about HTTP, HTML or the CLI.
"""

from __future__ import annotations

from functools import wraps
from pathlib import Path

from config import Settings, ensure_directories, get_settings
from core.ai_provider import AIProvider, get_provider
from core.analyzer import analyze_content
from core.change_report import build_before_after, build_change_report
from core.errors import AppError
from core.rewriter import rewrite_content
from exports import exporter
from processors import (
    ExtractedDocument,
    csv_processor,
    detect_type,
    docx_processor,
    pdf_processor,
    text_processor,
    xlsx_processor,
)
from reports import report_generator

# Rewriting tabular files sends one small request per distinct cell.
CELL_REWRITE_WARNING_THRESHOLD = 150


def safe(func):
    """Turn expected AppErrors into `{"ok": False, "error": {...}}` responses."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except AppError as exc:
            return exc.to_dict()
        except Exception as exc:  # last-resort guard: never crash the caller
            return {
                "ok": False,
                "error": {
                    "code": "unexpected_error",
                    "message": "An unexpected internal error occurred.",
                    "detail": f"{type(exc).__name__}: {exc}",
                },
            }

    return wrapper


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _context(settings: Settings | None) -> tuple[Settings, AIProvider]:
    settings = settings or get_settings()
    return settings, get_provider(settings)


def _extract(path: str | Path) -> ExtractedDocument:
    """Dispatch extraction by file extension."""
    kind = detect_type(path)
    extractors = {
        "text": text_processor.extract,
        "pdf": pdf_processor.extract,
        "docx": docx_processor.extract,
        "csv": csv_processor.extract,
        "xlsx": xlsx_processor.extract,
    }
    if kind not in extractors:
        from core.errors import UnsupportedFileError

        raise UnsupportedFileError(f"Unsupported file: {Path(path).name}")
    return extractors[kind](path)


def _analysis_payload(document: ExtractedDocument, settings, provider) -> dict:
    label = document.metadata.get("file_name", "text input")
    analysis = analyze_content(
        document.require_text(), settings, provider, source_label=label
    )
    report = report_generator.build_report(
        source_label=label,
        input_type=document.file_type,
        analysis=analysis,
        extraction_metadata=document.metadata,
        warnings=document.warnings,
    )
    return {
        "ok": True,
        "input_type": document.file_type,
        "source": label,
        "extraction": {
            "metadata": document.metadata,
            "warnings": document.warnings,
        },
        "analysis": analysis,
        "report": report,
    }


def _rewrite_payload(
    document: ExtractedDocument,
    settings,
    provider,
    include_analysis: bool,
) -> dict:
    label = document.metadata.get("file_name", "text input")
    text = document.require_text()

    analysis = (
        analyze_content(text, settings, provider, source_label=label)
        if include_analysis
        else None
    )
    rewrite = rewrite_content(text, settings, provider, source_label=label)
    changes = build_change_report(rewrite)
    before_after = build_before_after(rewrite, analysis)

    report = report_generator.build_report(
        source_label=label,
        input_type=document.file_type,
        analysis=analysis,
        rewrite=rewrite,
        change_report=changes,
        extraction_metadata=document.metadata,
        warnings=document.warnings,
    )
    return {
        "ok": True,
        "input_type": document.file_type,
        "source": label,
        "extraction": {"metadata": document.metadata, "warnings": document.warnings},
        "analysis": analysis,
        "rewrite": rewrite,
        "changes": changes,
        "before_after": before_after,
        "report": report,
    }


def _rewrite_cells(segments: list[dict], settings, provider) -> tuple[dict, list[dict], list[str]]:
    """
    Rewrite tabular cells one at a time so a cell's text can never land in the
    wrong row.  Identical cell values are rewritten once and reused.

    Returns `(text_by_original, all_changes, warnings)`.
    """
    warnings: list[str] = []
    distinct = {segment["text"] for segment in segments}
    if len(distinct) > CELL_REWRITE_WARNING_THRESHOLD:
        warnings.append(
            f"{len(distinct)} distinct text cells were rewritten, which means "
            f"{len(distinct)} model requests. Large files take a while."
        )

    cache: dict[str, str] = {}
    changes: list[dict] = []
    failures = 0

    for original in distinct:
        try:
            result = rewrite_content(original, settings, provider, source_label="cell")
        except AppError:
            failures += 1
            continue
        cache[original] = result["rewritten"]
        changes.extend(build_change_report(result)["changes"])

    if failures:
        warnings.append(f"{failures} cell(s) could not be rewritten and were left as-is.")
    return cache, changes, warnings


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------
@safe
def analyze_text(text: str, settings: Settings | None = None) -> dict:
    """Analyse raw text supplied by the user."""
    settings, provider = _context(settings)
    document = text_processor.extract_from_string(text)
    return _analysis_payload(document, settings, provider)


@safe
def rewrite_text(
    text: str, settings: Settings | None = None, include_analysis: bool = True
) -> dict:
    """Rewrite raw text and return original, rewrite, changes and analysis."""
    settings, provider = _context(settings)
    document = text_processor.extract_from_string(text)
    return _rewrite_payload(document, settings, provider, include_analysis)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
@safe
def analyze_pdf(path: str | Path, settings: Settings | None = None) -> dict:
    settings, provider = _context(settings)
    return _analysis_payload(pdf_processor.extract(path), settings, provider)


@safe
def rewrite_pdf(
    path: str | Path,
    settings: Settings | None = None,
    include_analysis: bool = True,
    write_pdf: bool = True,
) -> dict:
    """Rewrite a PDF's text and (optionally) render a new, text-only PDF."""
    settings, provider = _context(settings)
    document = pdf_processor.extract(path)
    payload = _rewrite_payload(document, settings, provider, include_analysis)

    if write_pdf:
        source = Path(path)
        destination = exporter.export_pdf(
            payload["rewrite"]["rewritten"],
            f"{source.stem}_natural_rewrite",
            title=f"Natural rewrite - {source.name}",
        )
        payload["output_file"] = str(destination)
        payload["report"]["warnings"].append(
            "The rewritten PDF is a clean, text-only rendering. Original layout, "
            "images and fonts are not reproduced; the source PDF is unchanged."
        )
    return payload


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------
@safe
def analyze_docx(path: str | Path, settings: Settings | None = None) -> dict:
    settings, provider = _context(settings)
    return _analysis_payload(docx_processor.extract(path), settings, provider)


@safe
def rewrite_docx(
    path: str | Path,
    settings: Settings | None = None,
    include_analysis: bool = True,
    write_file: bool = True,
) -> dict:
    """Rewrite a .docx and save a NEW document that keeps the original styling."""
    settings, provider = _context(settings)
    document = docx_processor.extract(path)
    payload = _rewrite_payload(document, settings, provider, include_analysis)

    if write_file:
        source = Path(path)
        rewritten_text = payload["rewrite"]["rewritten"]
        parts = [p for p in rewritten_text.split("\n\n") if p.strip()]

        if len(parts) == len(document.segments):
            destination = exporter.export_docx(
                source, document.segments, rewritten_text,
                stem=f"{source.stem}_natural_rewrite",
            )
        else:
            # Structure drifted: build a clean new document instead of risking
            # putting rewritten text into the wrong paragraph.
            destination = docx_processor.write_plain(
                rewritten_text,
                f"{source.stem}_natural_rewrite",
                title=f"Natural rewrite - {source.name}",
            )
            payload["report"]["warnings"].append(
                f"The rewrite returned {len(parts)} paragraphs for "
                f"{len(document.segments)} original segments, so a new plain "
                "document was produced instead of an in-place copy."
            )
        payload["output_file"] = str(destination)
    return payload


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
@safe
def analyze_csv(path: str | Path, settings: Settings | None = None) -> dict:
    settings, provider = _context(settings)
    return _analysis_payload(csv_processor.extract(path), settings, provider)


@safe
def rewrite_csv(
    path: str | Path,
    settings: Settings | None = None,
    include_analysis: bool = True,
) -> dict:
    """Rewrite only the natural-language cells of a CSV into a NEW file."""
    settings, provider = _context(settings)
    document = csv_processor.extract(path)
    source = Path(path)
    text = document.require_text()

    analysis = (
        analyze_content(text, settings, provider, source_label=source.name)
        if include_analysis
        else None
    )
    cache, changes, warnings = _rewrite_cells(document.segments, settings, provider)

    replacements = {
        (segment["column"], segment["row"]): cache[segment["text"]]
        for segment in document.segments
        if segment["text"] in cache
    }
    destination, applied = exporter.export_csv(
        source, replacements, stem=f"{source.stem}_natural_rewrite"
    )

    change_report = _tabular_change_report(changes, applied, "cell")
    report = report_generator.build_report(
        source_label=source.name,
        input_type="csv",
        analysis=analysis,
        change_report=change_report,
        extraction_metadata=document.metadata,
        warnings=document.warnings + warnings,
    )
    return {
        "ok": True,
        "input_type": "csv",
        "source": source.name,
        "analysis": analysis,
        "changes": change_report,
        "cells_changed": applied,
        "output_file": str(destination),
        "original_file": str(source),
        "report": report,
    }


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------
@safe
def analyze_xlsx(path: str | Path, settings: Settings | None = None) -> dict:
    settings, provider = _context(settings)
    return _analysis_payload(xlsx_processor.extract(path), settings, provider)


@safe
def rewrite_xlsx(
    path: str | Path,
    settings: Settings | None = None,
    include_analysis: bool = True,
) -> dict:
    """Rewrite only the natural-language cells of a workbook into a NEW file."""
    settings, provider = _context(settings)
    document = xlsx_processor.extract(path)
    source = Path(path)
    text = document.require_text()

    analysis = (
        analyze_content(text, settings, provider, source_label=source.name)
        if include_analysis
        else None
    )
    cache, changes, warnings = _rewrite_cells(document.segments, settings, provider)

    replacements = {
        (segment["sheet"], segment["coordinate"]): cache[segment["text"]]
        for segment in document.segments
        if segment["text"] in cache
    }
    destination, applied = exporter.export_xlsx(
        source, replacements, stem=f"{source.stem}_natural_rewrite"
    )

    change_report = _tabular_change_report(changes, applied, "cell")
    report = report_generator.build_report(
        source_label=source.name,
        input_type="xlsx",
        analysis=analysis,
        change_report=change_report,
        extraction_metadata=document.metadata,
        warnings=document.warnings + warnings,
    )
    return {
        "ok": True,
        "input_type": "xlsx",
        "source": source.name,
        "analysis": analysis,
        "changes": change_report,
        "cells_changed": applied,
        "output_file": str(destination),
        "original_file": str(source),
        "report": report,
    }


def _tabular_change_report(changes: list[dict], applied: list[dict], unit: str) -> dict:
    """Wrap per-cell edits in the same change-report shape used elsewhere."""
    major = sum(1 for c in changes if c.get("scale") == "major")
    by_type: dict[str, int] = {}
    for change in changes:
        key = change.get("change_type", "Readability improvement")
        by_type[key] = by_type.get(key, 0) + 1

    return {
        "summary": {
            "total_changes": len(changes),
            "major_changes": major,
            "minor_changes": len(changes) - major,
            "changes_by_type": by_type,
            "meaning_preservation_status": (
                f"Only natural-language {unit}s were rewritten; numbers, IDs, dates, "
                "formulas and non-text values were left untouched."
            ),
            "facts_preserved_status": (
                f"{len(applied)} {unit}(s) changed in the new file; the original file "
                "was not modified."
            ),
            "original_word_count": sum(len(a["original"].split()) for a in applied),
            "rewritten_word_count": sum(len(a["rewritten"].split()) for a in applied),
            "length_ratio": 0.0,
            "verification_notes": [],
            "model_preservation_notes": "",
        },
        "changes": changes,
        "examples": [
            {
                "original": item["original"],
                "rewritten": item["rewritten"],
                "change_type": "Cell rewrite",
                "reason": (
                    f"Sheet {item['sheet']} cell {item['cell']}"
                    if "sheet" in item
                    else f"Column '{item['column']}', row {item['row']}"
                ),
            }
            for item in applied[:10]
        ],
        "cells_changed": applied,
    }


# ---------------------------------------------------------------------------
# Generic dispatch
# ---------------------------------------------------------------------------
@safe
def analyze_file(path: str | Path, settings: Settings | None = None) -> dict:
    """Analyse any supported file, chosen by extension."""
    settings, provider = _context(settings)
    return _analysis_payload(_extract(path), settings, provider)


def rewrite_file(
    path: str | Path,
    settings: Settings | None = None,
    include_analysis: bool = True,
) -> dict:
    """Rewrite any supported file, chosen by extension."""
    kind = detect_type(path)
    handlers = {
        "text": lambda: rewrite_text(
            Path(path).read_text(encoding="utf-8", errors="replace"),
            settings,
            include_analysis,
        ),
        "pdf": lambda: rewrite_pdf(path, settings, include_analysis),
        "docx": lambda: rewrite_docx(path, settings, include_analysis),
        "csv": lambda: rewrite_csv(path, settings, include_analysis),
        "xlsx": lambda: rewrite_xlsx(path, settings, include_analysis),
    }
    if kind not in handlers:
        return {
            "ok": False,
            "error": {
                "code": "unsupported_file_type",
                "message": f"Unsupported file: {Path(path).name}",
                "detail": "Supported: .txt, .md, .pdf, .docx, .csv, .xlsx",
            },
        }
    return handlers[kind]()


# ---------------------------------------------------------------------------
# Reporting and exporting
# ---------------------------------------------------------------------------
@safe
def generate_change_report(rewrite_result: dict) -> dict:
    """Build a change report from a raw `rewrite_content(...)` result."""
    return {"ok": True, "changes": build_change_report(rewrite_result)}


@safe
def generate_report(
    result: dict,
    formats: tuple[str, ...] = ("json", "txt", "html"),
    stem: str | None = None,
) -> dict:
    """Write the report contained in an engine result to disk."""
    ensure_directories()
    report = result.get("report")
    if not report:
        return {
            "ok": False,
            "error": {
                "code": "no_report",
                "message": "This result does not contain a report to write.",
                "detail": None,
            },
        }
    stem = stem or exporter.default_stem(result.get("source", "result"), "report")
    written = exporter.export_report(report, stem, formats)
    return {"ok": True, "files": written}


@safe
def export_result(
    result: dict,
    formats: tuple[str, ...] = ("txt", "json", "html"),
    stem: str | None = None,
) -> dict:
    """
    Export everything useful from a result: rewritten text, JSON payload and
    the readable report.  Returns `{"files": {...}}`.
    """
    ensure_directories()
    stem = stem or exporter.default_stem(result.get("source", "result"), "result")
    files: dict[str, str] = {}

    rewritten = (result.get("rewrite") or {}).get("rewritten", "")
    if rewritten and "txt" in formats:
        files["rewritten_txt"] = str(exporter.export_text(rewritten, f"{stem}_rewritten"))

    if "json" in formats:
        files["result_json"] = str(exporter.export_json(result, f"{stem}_full"))

    if result.get("report"):
        report_formats = tuple(f for f in formats if f in {"json", "txt", "html", "pdf"})
        if report_formats:
            for key, path in exporter.export_report(
                result["report"], f"{stem}_report", report_formats
            ).items():
                files[f"report_{key}"] = path

    if result.get("output_file"):
        files["rewritten_document"] = result["output_file"]

    return {"ok": True, "files": files}
