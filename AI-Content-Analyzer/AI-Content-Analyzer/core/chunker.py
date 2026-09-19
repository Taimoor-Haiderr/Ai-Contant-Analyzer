"""
Chunking.

Large documents are split into model-sized pieces *without* ever discarding
content.  Paragraph boundaries and paragraph order are preserved so the pieces
can be recombined into text that looks like the original.

Nothing here is ever truncated.  If a single paragraph is bigger than the chunk
limit it is split on sentence boundaries, and the resulting pieces are marked as
continuations so the joiner puts them back together with a space instead of a
blank line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[A-Z0-9])")


@dataclass
class Chunk:
    """One piece of the document, in reading order."""

    index: int
    text: str
    paragraph_count: int
    starts_new_paragraph: bool = True   # False => continuation of previous chunk
    was_hard_split: bool = False        # True => a paragraph had to be broken up
    warnings: list[str] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def word_count(self) -> int:
        return len(self.text.split())


def split_paragraphs(text: str) -> list[str]:
    """Split on blank lines, dropping empty fragments but keeping order."""
    return [p.strip() for p in PARAGRAPH_SPLIT.split(text or "") if p.strip()]


def split_sentences(text: str) -> list[str]:
    """Rough sentence splitter, good enough for size control."""
    parts = SENTENCE_SPLIT.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def _split_long_paragraph(paragraph: str, max_chars: int) -> list[str]:
    """Break one oversized paragraph into sentence-aligned pieces."""
    pieces: list[str] = []
    buffer = ""
    for sentence in split_sentences(paragraph):
        # A single monstrous sentence (no punctuation) still has to be cut.
        while len(sentence) > max_chars:
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            if buffer:
                pieces.append(buffer.strip())
                buffer = ""
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()

        if buffer and len(buffer) + len(sentence) + 1 > max_chars:
            pieces.append(buffer.strip())
            buffer = sentence
        else:
            buffer = f"{buffer} {sentence}".strip()

    if buffer.strip():
        pieces.append(buffer.strip())
    return pieces


def chunk_text(text: str, max_chars: int = 6000) -> list[Chunk]:
    """
    Split `text` into chunks of at most ~`max_chars` characters.

    Returns an ordered list of Chunk objects.  Joining them with
    `join_chunks(...)` reproduces the original paragraph layout.
    """
    max_chars = max(500, int(max_chars))
    paragraphs = split_paragraphs(text)
    chunks: list[Chunk] = []

    buffer: list[str] = []
    buffer_len = 0

    def flush(starts_new: bool = True, hard_split: bool = False) -> None:
        nonlocal buffer, buffer_len
        if not buffer:
            return
        chunks.append(
            Chunk(
                index=len(chunks),
                text="\n\n".join(buffer),
                paragraph_count=len(buffer),
                starts_new_paragraph=starts_new,
                was_hard_split=hard_split,
            )
        )
        buffer = []
        buffer_len = 0

    for paragraph in paragraphs:
        if len(paragraph) <= max_chars:
            if buffer and buffer_len + len(paragraph) + 2 > max_chars:
                flush()
            buffer.append(paragraph)
            buffer_len += len(paragraph) + 2
            continue

        # Oversized paragraph: flush what we have, then emit standalone pieces.
        flush()
        pieces = _split_long_paragraph(paragraph, max_chars)
        for position, piece in enumerate(pieces):
            chunks.append(
                Chunk(
                    index=len(chunks),
                    text=piece,
                    paragraph_count=1,
                    starts_new_paragraph=(position == 0),
                    was_hard_split=True,
                    warnings=(
                        ["A long paragraph was split across chunks."]
                        if position > 0
                        else []
                    ),
                )
            )

    flush()

    if not chunks and (text or "").strip():
        # Text with no blank lines at all and shorter than the limit.
        chunks.append(
            Chunk(index=0, text=text.strip(), paragraph_count=1)
        )
    return chunks


def join_chunks(pieces: list[tuple[str, bool]]) -> str:
    """
    Rebuild a document from `(text, starts_new_paragraph)` pairs.

    Continuation pieces are joined with a space; new paragraphs with a blank
    line, which is exactly how `chunk_text` took the document apart.
    """
    output = ""
    for text, starts_new_paragraph in pieces:
        text = (text or "").strip()
        if not text:
            continue
        if not output:
            output = text
        elif starts_new_paragraph:
            output += "\n\n" + text
        else:
            output += " " + text
    return output
