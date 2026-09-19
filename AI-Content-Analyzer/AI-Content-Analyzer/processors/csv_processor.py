"""
CSV processing (pandas).

Only genuine natural-language cells are ever rewritten.  Numbers, IDs, codes,
booleans, dates and short label values are left exactly as they were, and column
names, column order and row order are preserved.  The original CSV is opened
read-only; the rewrite is always written to a new file.
"""

from __future__ import annotations

import re
from pathlib import Path

from config import OUTPUT_DIR
from core.errors import CorruptFileError, EmptyContentError, ExtractionError
from processors import (
    ExtractedDocument,
    normalize_text,
    resolve_input,
    unique_output_path,
)

try:
    import pandas as pd
except ImportError as exc:  # pragma: no cover - dependency guard
    raise ExtractionError(
        "pandas is not installed.", "Run: pip install -r requirements.txt"
    ) from exc

MIN_WORDS_PER_CELL = 4          # below this a cell is treated as a label, not prose
MIN_AVG_WORDS_PER_COLUMN = 3.0

ID_NAME_PATTERN = re.compile(
    r"^(id|.*_id|uuid|guid|code|sku|ref|reference|key|hash|url|link|email|phone|"
    r"date|datetime|timestamp|created.*|updated.*|price|amount|qty|quantity|"
    r"count|total|score|rating|year|month|day)$",
    re.IGNORECASE,
)
NUMERIC_LIKE = re.compile(r"^[\s$€£₹%+-]*[\d.,]+\s*[%a-zA-Z]{0,3}$")
DATE_LIKE = re.compile(
    r"^\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}([ T]\d{1,2}:\d{2}(:\d{2})?)?$"
)
ENCODINGS = ("utf-8", "utf-8-sig", "cp1252", "latin-1")


def _read(source: Path) -> "pd.DataFrame":
    last_error: Exception | None = None
    for encoding in ENCODINGS:
        try:
            return pd.read_csv(source, dtype=str, keep_default_na=False, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        except pd.errors.EmptyDataError as exc:
            raise EmptyContentError(
                f"'{source.name}' contains no data.", str(exc)
            ) from exc
        except pd.errors.ParserError as exc:
            raise CorruptFileError(
                f"'{source.name}' could not be parsed as CSV.",
                "Check for unbalanced quotes or inconsistent column counts.",
            ) from exc
    raise CorruptFileError(
        f"'{source.name}' could not be decoded.", str(last_error)
    )


def is_rewritable_cell(value: str) -> bool:
    """True when a single cell looks like natural-language prose."""
    text = (value or "").strip()
    if not text:
        return False
    if NUMERIC_LIKE.match(text) or DATE_LIKE.match(text):
        return False
    if text.startswith(("http://", "https://", "www.")) or "@" in text.split()[0]:
        return False
    return len(text.split()) >= MIN_WORDS_PER_CELL


def detect_text_columns(frame: "pd.DataFrame") -> list[str]:
    """Return the columns whose cells are mostly natural language."""
    text_columns: list[str] = []
    for column in frame.columns:
        if ID_NAME_PATTERN.match(str(column).strip()):
            continue
        values = [str(v).strip() for v in frame[column].tolist() if str(v).strip()]
        if not values:
            continue
        rewritable = [v for v in values if is_rewritable_cell(v)]
        if not rewritable:
            continue
        average_words = sum(len(v.split()) for v in rewritable) / len(rewritable)
        share = len(rewritable) / len(values)
        if average_words >= MIN_AVG_WORDS_PER_COLUMN and share >= 0.3:
            text_columns.append(str(column))
    return text_columns


def extract(path: str | Path) -> ExtractedDocument:
    """Read a CSV and collect its natural-language cells."""
    source = resolve_input(path)
    frame = _read(source)

    if frame.empty:
        raise EmptyContentError(f"'{source.name}' has no rows.")

    text_columns = detect_text_columns(frame)
    segments: list[dict] = []
    for column in text_columns:
        for row_index, value in enumerate(frame[column].tolist()):
            text = str(value).strip()
            if is_rewritable_cell(text):
                segments.append(
                    {
                        "kind": "cell",
                        "column": column,
                        "row": row_index,
                        "text": text,
                        "word_count": len(text.split()),
                    }
                )

    combined = normalize_text("\n\n".join(s["text"] for s in segments))
    warnings: list[str] = []
    if not text_columns:
        warnings.append(
            "No natural-language columns were detected; this file looks purely "
            "numeric or categorical."
        )

    return ExtractedDocument(
        text=combined,
        source_path=source,
        file_type="csv",
        segments=segments,
        metadata={
            "file_name": source.name,
            "row_count": int(frame.shape[0]),
            "column_count": int(frame.shape[1]),
            "columns": [str(c) for c in frame.columns],
            "text_columns": text_columns,
            "rewritable_cells": len(segments),
        },
        warnings=warnings,
    )


def write_rewritten(
    source_path: str | Path,
    replacements: dict[tuple[str, int], str],
    stem: str | None = None,
    output_dir: Path | None = None,
) -> tuple[Path, list[dict]]:
    """
    Write a NEW csv with the given cell replacements applied.

    `replacements` is keyed by `(column_name, row_index)`.
    Returns `(path, applied_changes)`.
    """
    source = resolve_input(source_path)
    frame = _read(source)

    directory = Path(output_dir) if output_dir else OUTPUT_DIR
    stem = stem or f"{source.stem}_natural_rewrite"
    destination = unique_output_path(directory, stem, ".csv")

    applied: list[dict] = []
    for (column, row_index), new_value in replacements.items():
        if column not in frame.columns or row_index >= len(frame):
            continue
        old_value = str(frame.at[frame.index[row_index], column])
        new_value = (new_value or "").strip()
        if not new_value or new_value == old_value:
            continue
        frame.at[frame.index[row_index], column] = new_value
        applied.append(
            {"column": column, "row": row_index, "original": old_value, "rewritten": new_value}
        )

    frame.to_csv(destination, index=False, encoding="utf-8")
    return destination, applied
