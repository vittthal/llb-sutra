"""Syllabus documents -> subject / module / topic rows.

Two sources, because Semester V straddles a syllabus revision:

  * the MU revision circular carries the NEW criminal paper (BNSS + JJ Act + POCSO),
    with module-wise section ranges
  * the full programme syllabus carries CPC, Labour Law II and Public International Law

Both are messy in different ways. The circular is born-digital but contains syllabi for
many programmes, so the right course block has to be isolated first. The full syllabus
is a scan, so OCR debris ("ase - 2 PRINCIPAL ane ee RR. Tiwari College") is interleaved
with real content and page furniture repeats mid-sentence.

The parser therefore does the least clever thing that survives that noise: locate a
course block by its title, split it on MODULE markers, and keep numbered sub-topics
(1.1, 2.3) where the document numbers them. It does not try to invent topic boundaries
where the source has none - a syllabus with slightly coarse modules is useful, while an
invented topic tree would be actively misleading to someone revising from it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# "MODULE 1;"  "MODULE - 2"  "Module 3:"  "MODULE-IV"
MODULE_RE = re.compile(
    r"MODULE\s*[-–—]?\s*(\d+|[IVX]{1,4})\s*[;:.\-]?\s*",
    re.IGNORECASE,
)

# Numbered sub-topics: "2.1 Parties to a suit", "1.3.3 Challenges to State Sovereignty"
TOPIC_RE = re.compile(r"(?:(?<=\s)|^)(\d{1,2}(?:\.\d{1,2}){1,2})\s+(?=[A-Za-z])")

# Section ranges quoted in module headings: "(Section 2-Section 25)", "Section 35 to 62"
SECTION_RANGE_RE = re.compile(
    r"Sections?\s*(\d{1,3}[A-Z]?)\s*(?:-|–|—|to)\s*(?:Section\s*)?(\d{1,3}[A-Z]?)",
    re.IGNORECASE,
)

_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8}

# Where each subject's course block starts. Ordered alternatives: first match wins.
COURSE_TITLE_PATTERNS: dict[str, list[str]] = {
    "CPC": [r"CIVIL PROCEDURE CODE\s*,?\s*1908\s*AND\s*LIMITATION ACT"],
    "BNSS": [r"BHARATIYA NAGARIK SURAKSHA SANHITA\s*2023\s*,?\s*THE JUVENILE"],
    "LABOUR2": [
        r"LABOUR LAW AND INDUSTRIAL RELATIONS\s*[-–—]?\s*II\b",
        r"LABOUR LAW\s*&\s*INDUSTRIAL RELATIONS\s*[-–—]?\s*II\b",
    ],
    "PIL": [r"PUBLIC INTERNATIONAL LAW"],
}

# A course block ends at the next course, which these markers announce.
# A reading list reliably ends a course block, and matters more than the next course
# header: without it a block runs on into the following subject and its modules get
# attributed to the wrong paper (PIL picking up BNSS trial procedure, for instance).
BLOCK_END_RE = re.compile(
    r"SUGGESTED READINGS|RECOMMENDED (?:RESOURCES|READINGS)|REFERENCE(?:S|D BOOKS)?\s*[:\-]"
    r"|Bare Acts\s*:|Course Title\s*[-:]|PROGRAM(?:ME)?\s*:|Semester\s*:\s*[IVX]",
    re.IGNORECASE,
)

_NOISE_RE = re.compile(
    r"(?:PRINCIPAL|Tiwari College|College of E\w*|ane\s*-\s*\d+|"
    r"eeeee+|_{3,}|Page\s*\d+\s*of\s*\d+)[^A-Za-z0-9]*",
    re.IGNORECASE,
)


@dataclass
class ParsedTopic:
    number: str | None
    title: str


@dataclass
class ParsedModule:
    number: int
    title: str
    text: str
    section_from: str | None = None
    section_to: str | None = None
    topics: list[ParsedTopic] = field(default_factory=list)


def clean(text: str) -> str:
    text = _NOISE_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def find_course_block(text: str, subject_code: str) -> str | None:
    """Isolate one subject's course block from a multi-programme document."""
    for pattern in COURSE_TITLE_PATTERNS.get(subject_code, []):
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            continue
        start = m.end()
        nxt = BLOCK_END_RE.search(text, start + 200)
        # Cap the fallback window tightly; an unbounded block swallows the next course.
        end = nxt.start() if nxt else min(len(text), start + 6000)
        return text[start:end]
    return None


def _module_number(raw: str) -> int | None:
    if raw.isdigit():
        return int(raw)
    return _ROMAN.get(raw.upper())


def _split_topics(body: str) -> list[ParsedTopic]:
    marks = list(TOPIC_RE.finditer(body))
    topics: list[ParsedTopic] = []
    for i, m in enumerate(marks):
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        title = body[start:end].strip(" .;,-")
        if 3 <= len(title) <= 220:
            topics.append(ParsedTopic(number=m.group(1), title=title))
    return topics


def _heading_from(body: str) -> str:
    """Text before the first numbered topic is the module heading."""
    first_topic = TOPIC_RE.search(body)
    heading = body[: first_topic.start()] if first_topic else body[:90]
    heading = heading.strip(" .;:,-")
    if len(heading) > 110:
        heading = heading[:110].rsplit(" ", 1)[0]
    return heading


def parse_modules(block: str) -> list[ParsedModule]:
    """Recover modules from MODULE markers AND from topic numbering.

    Both are needed. OCR drops module headers - the scanned CPC syllabus keeps
    "MODULE 1;" and "MODULE 2;" but loses 3 and 4 entirely, so a marker-only parser
    reports a 4-module paper as 2 modules and quietly hides half the syllabus from
    someone revising. The topic numbers survive (2.8 is followed by 3.1), so a change
    in the major number is treated as a module boundary in its own right.
    """
    block = clean(block)
    marks = list(MODULE_RE.finditer(block))

    # 1. Modules announced by a MODULE marker.
    by_number: dict[int, ParsedModule] = {}
    for i, m in enumerate(marks):
        number = _module_number(m.group(1))
        if number is None or number in by_number:
            continue
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(block)
        body = block[start:end].strip()
        if len(body) < 20:
            continue
        rng = SECTION_RANGE_RE.search(body[:300])
        by_number[number] = ParsedModule(
            number=number,
            title=_heading_from(body),
            text=body[:4000],
            section_from=rng.group(1) if rng else None,
            section_to=rng.group(2) if rng else None,
        )

    # 2. Group every numbered topic by its major number; that is the module it belongs
    #    to, whether or not a header survived.
    topic_marks = list(TOPIC_RE.finditer(block))
    grouped: dict[int, list[ParsedTopic]] = {}
    for i, m in enumerate(topic_marks):
        major_str = m.group(1).split(".")[0]
        if not major_str.isdigit():
            continue
        major = int(major_str)
        start = m.end()
        end = topic_marks[i + 1].start() if i + 1 < len(topic_marks) else len(block)
        title = block[start:end].strip(" .;,-")
        if 3 <= len(title) <= 220:
            grouped.setdefault(major, []).append(ParsedTopic(m.group(1), title))

    for major, topics in grouped.items():
        if major in by_number:
            by_number[major].topics = topics
        elif 1 <= major <= 12:
            by_number[major] = ParsedModule(
                number=major,
                title="",  # filled in below from the first topic
                text=" ".join(t.title for t in topics)[:4000],
                topics=topics,
            )

    # 3. A module whose heading did not survive is named after its first topic, which
    #    is far more useful to a student than "Module 3".
    for mod in by_number.values():
        # Strip a leading topic number ("2.1Requisite Conditions" -> "Requisite
        # Conditions"); the module already displays its own number.
        mod.title = re.sub(r"^\d{1,2}(?:\.\d{1,2}){0,2}\.?\s*", "", mod.title).strip(" .;:,-")

    for number, mod in by_number.items():
        if len(mod.title) < 4:
            mod.title = mod.topics[0].title[:80] if mod.topics else f"Module {number}"

    return sorted(by_number.values(), key=lambda x: x.number)


def parse_subject(text: str, subject_code: str) -> list[ParsedModule]:
    block = find_course_block(text, subject_code)
    if block is None:
        return []
    return parse_modules(block)
