"""
Export layer.

One place that knows how to turn engine results into files on disk.  Every
function returns the `Path` it wrote, and every function writes to a NEW file
inside the output folder - originals are never modified.

A future HTTP layer can call these directly and stream the resulting file back
to the browser.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from config import OUTPUT_DIR, REPORT_DIR, ensure_directories
from core.errors import ExportError
from processors import unique_output_path
from reports import report_generator


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_stem(name: str) -> str:
    keep = "-_. "
    cleaned = "".join(c for c in name if c.isalnum() or c in keep).strip().replace(" ", "_")
    return cleaned or "result"


# ---------------------------------------------------------------------------
# Text / JSON
# ---------------------------------------------------------------------------
def export_text(content: str, stem: str, output_dir: Path | None = None) -> Path:
    """Write plain text (typically the rewritten content) to a .txt file."""
    ensure_directories()
    directory = Path(output_dir) if output_dir else OUTPUT_DIR
    destination = unique_output_path(directory, _safe_stem(stem), ".txt")
    try:
        destination.write_text(content or "", encoding="utf-8")
    except OSError as exc:
        raise ExportError("Could not write the text file.", str(exc)) from exc
    return destination


def export_json(data: dict, stem: str, output_dir: Path | None = None) -> Path:
    """Write any engine result as machine-readable JSON."""
    ensure_directories()
    directory = Path(output_dir) if output_dir else REPORT_DIR
    destination = unique_output_path(directory, _safe_stem(stem), ".json")
    try:
        destination.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except OSError as exc:
        raise ExportError("Could not write the JSON file.", str(exc)) from exc
    return destination


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def export_report(
    report: dict,
    stem: str,
    formats: tuple[str, ...] = ("json", "txt", "html"),
    output_dir: Path | None = None,
) -> dict[str, str]:
    """
    Write the report in several formats at once.

    Returns `{format: path}`.  PDF is attempted only if PyMuPDF is importable,
    and a PDF failure never aborts the other formats.
    """
    ensure_directories()
    directory = Path(output_dir) if output_dir else REPORT_DIR
    stem = _safe_stem(stem)
    written: dict[str, str] = {}

    for fmt in formats:
        fmt = fmt.lower()
        if fmt == "pdf":
            try:
                path = export_report_pdf(report, stem, directory)
                written["pdf"] = str(path)
            except Exception as exc:  # PDF is a nice-to-have, never fatal
                written["pdf_error"] = str(exc)
            continue
        destination = unique_output_path(directory, stem, f".{fmt}")
        try:
            report_generator.write_report(report, destination, fmt)
            written[fmt] = str(destination)
        except (OSError, ValueError) as exc:
            raise ExportError(f"Could not write the {fmt} report.", str(exc)) from exc

    return written


def export_report_pdf(report: dict, stem: str, output_dir: Path | None = None) -> Path:
    """Render the plain-text report into a simple PDF."""
    from processors import pdf_processor  # imported lazily: PyMuPDF is optional here

    directory = Path(output_dir) if output_dir else REPORT_DIR
    body = report_generator.render_txt(report)
    return pdf_processor.write_pdf(
        body,
        _safe_stem(stem),
        output_dir=directory,
        title="AI Content Analysis Report",
        font_size=9,
    )


# ---------------------------------------------------------------------------
# Rewritten documents
# ---------------------------------------------------------------------------
def export_docx(
    source_path: str | Path,
    segments: list[dict],
    rewritten_text: str,
    stem: str | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Write a rewritten .docx based on the original document's structure."""
    from processors import docx_processor

    ensure_directories()
    mapping = docx_processor.build_segment_map(segments, rewritten_text)
    return docx_processor.write_rewritten(
        source_path, mapping, stem=stem, output_dir=output_dir or OUTPUT_DIR
    )


def export_csv(
    source_path: str | Path,
    replacements: dict,
    stem: str | None = None,
    output_dir: Path | None = None,
) -> tuple[Path, list[dict]]:
    """Write a rewritten .csv, leaving numeric/ID/date columns untouched."""
    from processors import csv_processor

    ensure_directories()
    return csv_processor.write_rewritten(
        source_path, replacements, stem=stem, output_dir=output_dir or OUTPUT_DIR
    )


def export_xlsx(
    source_path: str | Path,
    replacements: dict,
    stem: str | None = None,
    output_dir: Path | None = None,
) -> tuple[Path, list[dict]]:
    """Write a rewritten workbook, preserving sheets, formulas and non-text cells."""
    from processors import xlsx_processor

    ensure_directories()
    return xlsx_processor.write_rewritten(
        source_path, replacements, stem=stem, output_dir=output_dir or OUTPUT_DIR
    )


def export_pdf(
    content: str,
    stem: str,
    title: str = "",
    output_dir: Path | None = None,
) -> Path:
    """Write rewritten content into a NEW, simple text-only PDF."""
    from processors import pdf_processor

    ensure_directories()
    return pdf_processor.write_pdf(
        content, _safe_stem(stem), output_dir=output_dir or OUTPUT_DIR, title=title
    )


def default_stem(source_name: str, kind: str) -> str:
    """Build a predictable output name, e.g. `assignment_natural_rewrite_20260918`."""
    base = _safe_stem(Path(source_name).stem or "result")
    return f"{base}_{kind}_{_stamp()}"
