"""Structure-aware chunking.

Fixed-size chunking is the default in most RAG tutorials and it is wrong for law. A
statutory section is a unit of meaning: split "Section 11 CPC" across two chunks and
neither half answers the question, while both half-match the query. So chunk boundaries
follow the document structure instead:

  bare_act / treaty  one chunk per section, never split mid-section
  judgment           per paragraph; headnote kept as its own chunk
  notes / textbook   per heading, ~800 token target with 100 token overlap
  pyq                per question
  syllabus           per module heading

Token counts are estimated, not tokenized. The estimate only needs to be good enough to
size chunks; the retrieval context cap is enforced separately and precisely.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TARGET_TOKENS = 800
OVERLAP_TOKENS = 100

# Numbered paragraphs in judgments: "12. The appellant contends ..."
JUDGMENT_PARA_RE = re.compile(r"^\s*(\d{1,3})\.\s+", re.MULTILINE)

# Headings in notes: markdown-ish, ALL CAPS lines, or "Q.1", "1.2 Topic"
HEADING_RE = re.compile(
    r"^(?:#{1,6}\s+.+|[A-Z][A-Z \-,&()/]{6,}|(?:\d+\.){1,3}\s+\S.{3,80})$",
    re.MULTILINE,
)

# Question papers: "Q.1", "Q 1.", "1.", "(a)"
PYQ_RE = re.compile(r"^\s*(?:Q\.?\s*\d+|[0-9]{1,2}\.)\s+", re.MULTILINE)


@dataclass
class Chunk:
    ord: int
    text: str
    heading: str | None = None
    n_tokens: int = 0


def estimate_tokens(text: str) -> int:
    """~1.3 tokens per whitespace word. Close enough for sizing decisions."""
    return max(1, int(len(text.split()) * 1.3))


def _split_on(text: str, pattern: re.Pattern[str]) -> list[str]:
    positions = [m.start() for m in pattern.finditer(text)]
    if not positions:
        return [text] if text.strip() else []
    if positions[0] != 0:
        positions.insert(0, 0)
    parts: list[str] = []
    for i, start in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(text)
        piece = text[start:end].strip()
        if piece:
            parts.append(piece)
    return parts


def _pack(parts: list[str], target: int, overlap: int) -> list[str]:
    """Group small parts up to `target` tokens, carrying `overlap` tokens forward."""
    packed: list[str] = []
    buffer: list[str] = []
    size = 0

    for part in parts:
        part_tokens = estimate_tokens(part)
        # An oversized single part is emitted whole rather than cut mid-thought.
        if part_tokens >= target:
            if buffer:
                packed.append("\n\n".join(buffer))
                buffer, size = [], 0
            packed.append(part)
            continue

        if size + part_tokens > target and buffer:
            packed.append("\n\n".join(buffer))
            # Carry the tail of the previous chunk forward so a boundary does not
            # orphan a sentence that answers the question.
            tail_words = " ".join(buffer).split()[-int(overlap / 1.3) :]
            buffer = [" ".join(tail_words)] if tail_words else []
            size = estimate_tokens(" ".join(buffer)) if buffer else 0

        buffer.append(part)
        size += part_tokens

    if buffer:
        packed.append("\n\n".join(buffer))
    return packed


def _first_line(text: str) -> str | None:
    for line in text.split("\n"):
        line = line.strip()
        if line:
            return line[:200]
    return None


def chunk_document(text: str, doc_type: str) -> list[Chunk]:
    """Split a document into chunks according to its type."""
    if doc_type in {"bare_act", "treaty"}:
        # Provisions are chunked by ingest.load directly from parsed sections, so a
        # whole-document call here means the parser found nothing; fall back to
        # paragraph packing rather than returning one enormous chunk.
        parts = [p.strip() for p in text.split("\n\n") if p.strip()]
        pieces = _pack(parts, TARGET_TOKENS, OVERLAP_TOKENS)
    elif doc_type == "judgment":
        pieces = _split_on(text, JUDGMENT_PARA_RE)
    elif doc_type == "pyq":
        pieces = _split_on(text, PYQ_RE)
    else:  # notes, textbook, syllabus
        sections = _split_on(text, HEADING_RE)
        pieces = _pack(sections, TARGET_TOKENS, OVERLAP_TOKENS)

    return [
        Chunk(ord=i, text=piece, heading=_first_line(piece), n_tokens=estimate_tokens(piece))
        for i, piece in enumerate(pieces)
        if piece.strip()
    ]


def chunk_provision(section_no: str, marginal_note: str | None, text: str, ord_: int) -> Chunk:
    """One provision, one chunk. The section number leads so lexical search hits it."""
    heading = f"Section {section_no}"
    if marginal_note:
        heading = f"{heading}. {marginal_note}"
    body = f"{heading}\n\n{text}"
    return Chunk(ord=ord_, text=body, heading=heading, n_tokens=estimate_tokens(body))
