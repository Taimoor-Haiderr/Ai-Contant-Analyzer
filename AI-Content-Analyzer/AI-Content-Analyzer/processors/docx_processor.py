"""
DOCX processing (python-docx).

Reading : headings, body paragraphs and table cells, in document order.
Writing : the original file is COPIED first, then the copy's text is replaced
          in place.  Styles, fonts, headings, numbering, images and tables
          therefore survive, and the original file is never opened for writing.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from config import OUTPUT_DIR
from core.errors import CorruptFileError, ExportError, ExtractionError
from processors import (
    ExtractedDocument,
    normalize_text,
    resolve_input,
    unique_output_path,
)

try:
    import docx
    from docx.document import Document as DocxDocument
except ImportError as exc:  # pragma: no cover - dependency guard
    raise ExtractionError(
        "python-docx is not installed.", "Run: pip install -r requirements.txt"
    ) from exc

MIN_WORDS_TO_REWRITE = 3


def _open(source: Path) -> "DocxDocument":
    try:
        return docx.Document(str(source))
    except Exception as exc:
        raise CorruptFileError(
            f"'{source.name}' could not be opened as a .docx file.",
            "It may be corrupted, password protected, or an old .doc file. "
            "Save it as .docx and try again.",
        ) from exc


def _iter_units(document: "DocxDocument"):
    """
    Yield (kind, locator, paragraph) for every text-bearing paragraph.

    `locator` identifies the paragraph so the rewriter can put text back.
    """
    for index, paragraph in enumerate(document.paragraphs):
        yield "paragraph", ("body", index), paragraph

    for t_index, table in enumerate(document.tables):
        for r_index, row in enumerate(table.rows):
            for c_index, cell in enumerate(row.cells):
                for p_index, paragraph in enumerate(cell.paragraphs):
                    yield (
                        "table_cell",
                        ("table", t_index, r_index, c_index, p_index),
                        paragraph,
                    )


def extract(path: str | Path) -> ExtractedDocument:
    """Extract headings, paragraphs and table text from a .docx file."""
    source = resolve_input(path)
    document = _open(source)

    segments: list[dict] = []
    text_parts: list[str] = []
    heading_count = 0

    for kind, locator, paragraph in _iter_units(document):
        content = (paragraph.text or "").strip()
        if not content:
            continue
        style = (paragraph.style.name if paragraph.style else "") or ""
        is_heading = style.lower().startswith("heading") or style.lower() == "title"
        heading_count += 1 if is_heading else 0
        segments.append(
            {
                "kind": "heading" if is_heading else kind,
                "locator": list(locator),
                "style": style,
                "text": content,
                "word_count": len(content.split()),
            }
        )
        text_parts.append(content)

    text = normalize_text("\n\n".join(text_parts))
    if not text.strip():
        raise ExtractionError(
            f"No text was found in '{source.name}'.",
            "The document may contain only images or drawings.",
        )

    return ExtractedDocument(
        text=text,
        source_path=source,
        file_type="docx",
        segments=segments,
        metadata={
            "file_name": source.name,
            "paragraph_count": len(document.paragraphs),
            "table_count": len(document.tables),
            "heading_count": heading_count,
            "text_segments": len(segments),
        },
    )


def _set_paragraph_text(paragraph, new_text: str) -> None:
    """Replace a paragraph's text while keeping the first run's formatting."""
    runs = paragraph.runs
    if not runs:
        paragraph.add_run(new_text)
        return
    runs[0].text = new_text
    for run in runs[1:]:
        run.text = ""


def write_rewritten(
    source_path: str | Path,
    segment_map: dict[str, str],
    stem: str | None = None,
    output_dir: Path | None = None,
) -> Path:
    """
    Produce a NEW .docx containing the rewritten text.

    `segment_map` maps the *original* segment text to its replacement, which
    keeps the API simple for callers that rewrote paragraph by paragraph.
    """
    source = resolve_input(source_path)
    directory = Path(output_dir) if output_dir else OUTPUT_DIR
    stem = stem or f"{source.stem}_natural_rewrite"
    destination = unique_output_path(directory, stem, ".docx")

    try:
        shutil.copyfile(source, destination)     # original stays untouched
    except OSError as exc:
        raise ExportError("Could not create the output document.", str(exc)) from exc

    document = _open(destination)
    replaced = 0
    for _kind, _locator, paragraph in _iter_units(document):
        original = (paragraph.text or "").strip()
        if not original:
            continue
        replacement = segment_map.get(original)
        if replacement and replacement.strip() and replacement.strip() != original:
            _set_paragraph_text(paragraph, replacement.strip())
            replaced += 1

    try:
        document.save(str(destination))
    except OSError as exc:
        raise ExportError("Could not save the output document.", str(exc)) from exc

    return destination


def write_plain(
    text: str,
    stem: str,
    output_dir: Path | None = None,
    title: str = "",
) -> Path:
    """
    Build a brand-new .docx from plain text.

    Used as a safe fallback when the rewritten paragraph count no longer lines
    up with the original document, so the engine never risks putting the wrong
    text into the wrong paragraph.
    """
    directory = Path(output_dir) if output_dir else OUTPUT_DIR
    destination = unique_output_path(directory, stem, ".docx")
    document = docx.Document()
    if title:
        document.add_heading(title, level=1)
    for paragraph in (text or "").split("\n\n"):
        document.add_paragraph(paragraph.strip())
    try:
        document.save(str(destination))
    except OSError as exc:
        raise ExportError("Could not save the output document.", str(exc)) from exc
    return destination


def build_segment_map(segments: list[dict], rewritten_text: str) -> dict[str, str]:
    """
    Pair each extracted segment with its rewritten counterpart.

    Extraction joined the segments with blank lines, so the rewrite is split the
    same way.  If the counts differ (a model merged or split a paragraph) the
    pairing stops at the shorter list rather than misaligning the document.
    """
    rewritten_parts = [
        part.strip() for part in rewritten_text.split("\n\n") if part.strip()
    ]
    mapping: dict[str, str] = {}
    for segment, replacement in zip(segments, rewritten_parts):
        mapping[segment["text"]] = replacement
    return mapping
