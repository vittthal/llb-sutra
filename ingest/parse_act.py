"""Bare act text -> section-level `provision` rows.

Indian bare acts follow a fairly consistent typographic convention:

    11. Res judicata.—No Court shall try any suit or issue in which ...
    41A. Notice of appearance before police officer.—(1) The police officer shall ...
    2. Definitions.—In this Act, unless the context otherwise requires,—

so a section starts at line-begin with a number (optionally suffixed with letters for
inserted sections such as 41A or 197B), a full stop, the marginal note, and then an
em-dash before the operative text.

Two traps this handles:

  * ARRANGEMENT OF SECTIONS — every bare act opens with a table of contents using the
    same "11. Res judicata" shape. Parsing it produces a full set of duplicate sections
    with no text. We detect and skip it.
  * Running headers/footers repeated on each page get filtered as short repeated lines.

Known limitation: the CPC First Schedule (Orders and Rules, e.g. "Order VII Rule 11")
has a different structure and is NOT parsed by this module yet. Orders matter for the
CPC paper, so this is the first extension to make — tracked as a TODO below.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

# 11.  |  41A.  |  197B.
SECTION_RE = re.compile(
    r"^\s*(?P<num>\d{1,3}[A-Z]{0,2})\.\s*(?P<rest>\S.*)$",
    re.MULTILINE,
)

# Marginal note ends at an em dash, en dash, or double hyphen.
NOTE_SPLIT_RE = re.compile(r"^(?P<note>.{2,160}?)\s*[—–]\s*(?P<body>.*)$", re.DOTALL)

TOC_MARKERS = (
    "ARRANGEMENT OF SECTIONS",
    "ARRANGEMENT OF CLAUSES",
    "TABLE OF CONTENTS",
    "CONTENTS",
)


@dataclass
class ParsedProvision:
    section_no: str
    marginal_note: str | None
    text: str
    ord: int


def _strip_toc(text: str) -> str:
    """Drop the arrangement-of-sections block that opens most bare acts.

    Strategy: find the last TOC marker, then find where the enacting text begins.
    The body proper reliably starts after a line containing "BE it enacted" or the
    first section that carries an em-dash (a TOC entry never does).
    """
    upper = text.upper()
    last_marker = -1
    for marker in TOC_MARKERS:
        pos = upper.rfind(marker)
        last_marker = max(last_marker, pos)
    if last_marker == -1:
        return text

    tail = text[last_marker:]
    enact = re.search(r"BE it enacted|BE IT ENACTED", tail)
    if enact:
        return tail[enact.start() :]

    # No enacting formula (amendment acts, codes): fall back to the first section
    # that has an em-dash, which is the first real operative provision.
    first_real = re.search(r"^\s*\d{1,3}[A-Z]{0,2}\.\s*.{2,160}?[—–]", tail, re.MULTILINE)
    if first_real:
        return tail[first_real.start() :]
    return text


def _strip_running_headers(text: str) -> str:
    """Remove short lines that repeat on many pages (headers/footers)."""
    lines = text.split("\n")
    short = [ln.strip() for ln in lines if 0 < len(ln.strip()) <= 80]
    counts = Counter(short)
    # A line repeated more than 5 times and short is a header, not substance.
    noise = {ln for ln, n in counts.items() if n > 5}
    if not noise:
        return text
    return "\n".join(ln for ln in lines if ln.strip() not in noise)


def parse(text: str, *, strip_toc: bool = True) -> list[ParsedProvision]:
    if strip_toc:
        text = _strip_toc(text)
    text = _strip_running_headers(text)

    matches = list(SECTION_RE.finditer(text))
    provisions: list[ParsedProvision] = []
    seen: set[str] = set()

    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)

        num = match.group("num")
        # Slice from the ORIGINAL text, never from a stripped copy: stripping shifts
        # every offset left and silently eats the first character of the marginal note.
        rest = text[match.start("rest") : end].strip()

        note: str | None = None
        body = rest
        split = NOTE_SPLIT_RE.match(rest)
        if split:
            candidate = split.group("note").strip()
            # A marginal note is a short phrase, not a sentence of operative text.
            if len(candidate) <= 160 and candidate.count(".") <= 2:
                note = candidate.rstrip(".")
                body = split.group("body").strip()

        # A section with no body is a leftover TOC line; skip rather than store empty.
        if len(body) < 20:
            continue
        # Bare acts renumber across schedules; first occurrence wins.
        if num in seen:
            continue
        seen.add(num)

        provisions.append(
            ParsedProvision(
                section_no=num,
                marginal_note=note,
                text=body,
                ord=len(provisions),
            )
        )

    return provisions


# TODO: parse the CPC First Schedule (Orders and Rules). Shape is:
#   ORDER VII
#   RULE 11. Rejection of plaint.—The plaint shall be rejected in the following cases:—
# which needs a two-level section_no such as "O.7 R.11" to match how students cite it.
