"""
Plain text (.txt, .md) processing.

Reading is encoding-tolerant: UTF-8 first, then a few common fallbacks, then a
lossy read as a last resort (with a warning) so a stray byte never blocks the
whole job.
"""

from __future__ import annotations

from pathlib import Path

from config import OUTPUT_DIR
from core.errors import ExtractionError
from processors import (
    ExtractedDocument,
    normalize_text,
    resolve_input,
    unique_output_path,
)

ENCODINGS = ("utf-8", "utf-8-sig", "cp1252", "latin-1")


def extract(path: str | Path) -> ExtractedDocument:
    """Read a text file into an ExtractedDocument."""
    source = resolve_input(path)
    warnings: list[str] = []
    raw = None

    for encoding in ENCODINGS:
        try:
            raw = source.read_text(encoding=encoding)
            if encoding != "utf-8":
                warnings.append(f"File was decoded using '{encoding}'.")
            break
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            raise ExtractionError(
                f"Could not read '{source.name}'.", str(exc)
            ) from exc

    if raw is None:
        try:
            raw = source.read_text(encoding="utf-8", errors="replace")
            warnings.append(
                "Some characters could not be decoded and were replaced."
            )
        except OSError as exc:
            raise ExtractionError(
                f"Could not read '{source.name}'.", str(exc)
            ) from exc

    text = normalize_text(raw)
    return ExtractedDocument(
        text=text,
        source_path=source,
        file_type="text",
        metadata={"file_name": source.name, "bytes": source.stat().st_size},
        warnings=warnings,
    )


def extract_from_string(text: str, label: str = "text input") -> ExtractedDocument:
    """Wrap raw user-typed/pasted text in the same structure."""
    return ExtractedDocument(
        text=normalize_text(text),
        source_path=None,
        file_type="text",
        metadata={"file_name": label},
    )


def write_text(content: str, stem: str, output_dir: Path | None = None) -> Path:
    """Write rewritten text to a NEW .txt file and return its path."""
    directory = Path(output_dir) if output_dir else OUTPUT_DIR
    destination = unique_output_path(directory, stem, ".txt")
    destination.write_text(content, encoding="utf-8")
    return destination
