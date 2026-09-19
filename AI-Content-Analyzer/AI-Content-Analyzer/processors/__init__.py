"""
File processors.

Every processor exposes the same two ideas:

    extract(path)  -> ExtractedDocument      (read only, never writes)
    write_*(...)   -> Path                   (always a NEW file)

No processor ever opens an original file in write mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.errors import EmptyContentError, FileNotFoundErrorApp, UnsupportedFileError

SUPPORTED_EXTENSIONS = {
    ".txt": "text",
    ".md": "text",
    ".pdf": "pdf",
    ".docx": "docx",
    ".csv": "csv",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
}


@dataclass
class ExtractedDocument:
    """Normalised view of any supported input file."""

    text: str                       # plain text used for analysis/rewriting
    source_path: Path | None = None
    file_type: str = "text"
    segments: list = field(default_factory=list)   # processor-specific detail
    metadata: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def require_text(self) -> str:
        if not self.text or not self.text.strip():
            raise EmptyContentError(
                "No usable text was found in this file.",
                f"File: {self.source_path.name if self.source_path else 'input'}",
            )
        return self.text


def resolve_input(path: str | Path) -> Path:
    """Validate that an input path exists and has a supported extension."""
    candidate = Path(path).expanduser()
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundErrorApp(f"File not found: {candidate}")
    suffix = candidate.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileError(
            f"Unsupported file type '{suffix or '(none)'}'.",
            "Supported types: " + ", ".join(sorted(SUPPORTED_EXTENSIONS)),
        )
    if candidate.stat().st_size == 0:
        raise EmptyContentError(f"The file is empty: {candidate.name}")
    return candidate


def detect_type(path: str | Path) -> str:
    """Return the processor key ('text', 'pdf', 'docx', 'csv', 'xlsx')."""
    return SUPPORTED_EXTENSIONS.get(Path(path).suffix.lower(), "")


def unique_output_path(directory: Path, stem: str, suffix: str) -> Path:
    """
    Build a non-colliding output path.

    Originals are never touched: if `stem+suffix` already exists a counter is
    appended instead of overwriting anything.
    """
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{stem}{suffix}"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def normalize_text(text: str) -> str:
    """
    Content normalisation step of the workflow.

    Unifies line endings, strips zero-width characters, collapses runs of blank
    lines and trims trailing spaces - without deleting real content.
    """
    if not text:
        return ""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = cleaned.replace("\u00a0", " ")
    for zero_width in ("\u200b", "\u200c", "\u200d", "\ufeff"):
        cleaned = cleaned.replace(zero_width, "")
    lines = [line.rstrip() for line in cleaned.split("\n")]
    cleaned = "\n".join(lines)
    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")
    return cleaned.strip()
