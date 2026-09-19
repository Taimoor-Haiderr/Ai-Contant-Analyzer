"""
PDF processing (PyMuPDF / fitz).

Reading  : page-by-page text extraction that keeps page and paragraph order.
Detection: a PDF whose pages carry images but almost no selectable text is
           reported as a scanned document instead of silently producing nothing.
Writing  : a NEW, simple, text-only PDF is generated for rewritten content.
           The original PDF is opened read-only and never modified.
"""

from __future__ import annotations

from pathlib import Path

from config import OUTPUT_DIR
from core.errors import CorruptFileError, ExtractionError, ScannedDocumentError
from processors import (
    ExtractedDocument,
    normalize_text,
    resolve_input,
    unique_output_path,
)

try:
    # PyMuPDF >= 1.24 prefers the `pymupdf` name; `fitz` is the legacy alias.
    import pymupdf as fitz
except ImportError:  # pragma: no cover - older PyMuPDF releases
    try:
        import fitz
    except ImportError as exc:
        raise ExtractionError(
            "PyMuPDF is not installed.", "Run: pip install -r requirements.txt"
        ) from exc

# Below this many characters per page, a page is treated as having no real text.
MIN_CHARS_PER_PAGE = 40


def _page_paragraphs(page) -> str:
    """
    Rebuild paragraphs from a page.

    PyMuPDF's "blocks" mode groups lines that belong together, which is a much
    better paragraph signal than raw line breaks.  Lines inside a block are
    joined with a space (de-hyphenating line-end breaks); blocks are separated
    by a blank line.  Falls back to plain text extraction if blocks are absent.
    """
    try:
        blocks = page.get_text("blocks") or []
    except Exception:
        blocks = []

    if not blocks:
        return page.get_text("text") or ""

    # blocks are (x0, y0, x1, y1, text, block_no, block_type); keep reading order
    text_blocks = [
        block[4] for block in sorted(blocks, key=lambda b: (round(b[1], 1), b[0]))
        if len(block) > 4 and isinstance(block[4], str) and block[4].strip()
    ]

    paragraphs: list[str] = []
    for block in text_blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        merged = ""
        for line in lines:
            if not merged:
                merged = line
            elif merged.endswith("-"):
                merged = merged[:-1] + line        # join a hyphenated break
            else:
                merged = f"{merged} {line}"
        if merged:
            paragraphs.append(merged)
    return "\n\n".join(paragraphs)


def extract(path: str | Path) -> ExtractedDocument:
    """Extract text from a PDF, preserving page and paragraph order."""
    source = resolve_input(path)

    try:
        document = fitz.open(source)
    except Exception as exc:  # PyMuPDF raises several unrelated types
        raise CorruptFileError(
            f"'{source.name}' could not be opened as a PDF.",
            "The file may be corrupted, encrypted or not a real PDF.",
        ) from exc

    if document.needs_pass:
        document.close()
        raise ExtractionError(
            f"'{source.name}' is password protected.",
            "Remove the password and try again.",
        )

    pages: list[dict] = []
    text_blocks: list[str] = []
    pages_with_images = 0
    warnings: list[str] = []

    try:
        for number, page in enumerate(document, start=1):
            page_text = normalize_text(_page_paragraphs(page))
            has_images = bool(page.get_images(full=True))
            pages_with_images += 1 if has_images else 0
            pages.append(
                {
                    "page": number,
                    "characters": len(page_text),
                    "has_images": has_images,
                    "text": page_text,
                }
            )
            if page_text:
                text_blocks.append(page_text)
        page_count = document.page_count
        metadata = dict(document.metadata or {})
    except Exception as exc:
        raise ExtractionError(
            f"Text extraction failed for '{source.name}'.", str(exc)
        ) from exc
    finally:
        document.close()

    combined = normalize_text("\n\n".join(text_blocks))
    empty_pages = sum(1 for p in pages if p["characters"] < MIN_CHARS_PER_PAGE)

    # Scanned / image-only detection.
    if not combined.strip():
        if pages_with_images:
            raise ScannedDocumentError(
                f"'{source.name}' appears to be a scanned PDF: its pages contain "
                "images but no selectable text.",
                "Run OCR on the file first (for example with OCRmyPDF or Adobe "
                "Acrobat), then analyse the OCR'd version.",
            )
        raise ExtractionError(
            f"No text could be extracted from '{source.name}'.",
            "The PDF contains no selectable text.",
        )

    if page_count and empty_pages / page_count > 0.5:
        warnings.append(
            f"{empty_pages} of {page_count} pages had little or no selectable text "
            "and may be scanned images."
        )

    return ExtractedDocument(
        text=combined,
        source_path=source,
        file_type="pdf",
        segments=pages,
        metadata={
            "file_name": source.name,
            "page_count": page_count,
            "pages_with_images": pages_with_images,
            "pdf_metadata": {
                k: v for k, v in metadata.items() if isinstance(v, str) and v
            },
        },
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
def write_pdf(
    text: str,
    stem: str,
    output_dir: Path | None = None,
    title: str = "",
    font_size: int = 11,
) -> Path:
    """
    Render plain text into a NEW A4 PDF.

    Deliberately simple: one column, wrapped lines, automatic pagination.  It
    does not try to clone the layout of an original PDF, because doing that
    reliably is out of scope for this project.
    """
    directory = Path(output_dir) if output_dir else OUTPUT_DIR
    destination = unique_output_path(directory, stem, ".pdf")

    page_width, page_height = fitz.paper_size("a4")
    margin = 56.0
    usable_width = page_width - (2 * margin)
    leading = font_size * 1.45
    font_name = "helv"

    document = fitz.open()
    page = document.new_page(width=page_width, height=page_height)
    cursor = margin

    def new_page() -> None:
        nonlocal page, cursor
        page = document.new_page(width=page_width, height=page_height)
        cursor = margin

    def write_line(line: str, size: int, bold: bool = False) -> None:
        nonlocal cursor
        if cursor + leading > page_height - margin:
            new_page()
        page.insert_text(
            (margin, cursor),
            line,
            fontsize=size,
            fontname="hebo" if bold else font_name,
        )
        cursor += size * 1.45

    def wrap(line: str, size: int, bold: bool) -> list[str]:
        name = "hebo" if bold else font_name
        words = line.split()
        if not words:
            return [""]
        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if fitz.get_text_length(trial, fontname=name, fontsize=size) <= usable_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    if title:
        for line in wrap(title, font_size + 4, True):
            write_line(line, font_size + 4, bold=True)
        cursor += leading * 0.5

    for paragraph in (text or "").split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        for raw_line in paragraph.split("\n"):
            for line in wrap(raw_line, font_size, False):
                write_line(line, font_size)
        cursor += leading * 0.6

    document.save(destination)
    document.close()
    return destination
