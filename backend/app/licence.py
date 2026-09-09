"""Copyright gating.

What the API is allowed to SERVE is decided here, at serialization time, by the
document's licence — never by an instruction in a prompt. A prompt instruction is not
a licence control: the model can ignore it, and a jailbreak can strip it.

The distinction that matters:

  * RETRIEVAL  — a chunk may always be retrieved and fed to the model as context.
  * SERVING    — what actually reaches the user's browser is capped by licence.

So a copyrighted textbook can still make the answer better without the platform ever
redistributing the book.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

Licence = Literal["public", "govt-public", "owned-licensed", "excerpt-only"]

# None means "no cap" — the text is public and may be served in full.
_MAX_CHARS: Final[dict[str, int | None]] = {
    "public": None,          # treaties, UN/ICJ material
    "govt-public": None,     # Indian bare acts and judgments
    "owned-licensed": 200,   # your legally-owned books and notes
    "excerpt-only": 50,      # most restricted
}

# Anything not in the table is treated as maximally restricted rather than public.
# An unknown licence is a bug, and the safe failure mode is to serve less, not more.
_FALLBACK_MAX_CHARS: Final[int] = 50


def max_chars(licence: str) -> int | None:
    """Characters of chunk text servable under this licence. None = unlimited."""
    if licence not in _MAX_CHARS:
        return _FALLBACK_MAX_CHARS
    return _MAX_CHARS[licence]


def is_full_text_servable(licence: str) -> bool:
    return max_chars(licence) is None


@dataclass(frozen=True)
class ServedChunk:
    """A chunk as it may leave the server."""

    chunk_id: int
    text: str
    truncated: bool
    licence: str
    citation: str


def serve_text(text: str, licence: str) -> tuple[str, bool]:
    """Apply the licence cap. Returns (text_to_serve, was_truncated)."""
    cap = max_chars(licence)
    if cap is None:
        return text, False
    if len(text) <= cap:
        return text, False
    # Trim at a word boundary where one is close by, so excerpts read as prose
    # rather than being cut mid-word.
    cut = text[:cap]
    space = cut.rfind(" ")
    if space > cap * 0.6:
        cut = cut[:space]
    return cut.rstrip() + "…", True


def serve_chunk(
    *,
    chunk_id: int,
    text: str,
    licence: str,
    citation: str,
) -> ServedChunk:
    served, truncated = serve_text(text, licence)
    return ServedChunk(
        chunk_id=chunk_id,
        text=served,
        truncated=truncated,
        licence=licence,
        citation=citation,
    )
