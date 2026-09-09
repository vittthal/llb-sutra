"""Question papers -> the `pyq` table, which powers the PYQ analytics feature.

Mumbai University 75-25 papers follow a stable shape:

    Q.1  Answer in one or two sentences        (many short sub-questions)
    Q.2  Write short notes (Any 2)             (a. b. c. d.)
    Q.3  Solve any two                         (problem sums)
    Q.4  Answer the following (Any three)      (long answers)

Two realities shape this parser:

  * The papers are photocopied scans, so OCR output is noisy. Stray characters
    ("oS ; = ", "~ a (tm) eo FP") appear between real questions. Text is cleaned but
    never rewritten - a question kept slightly noisy is useful; an invented one is not.
  * Marks are printed in the right margin and OCR mangles them badly ("(69)" where the
    paper says "(15)"). So marks are recorded ONLY when they parse unambiguously, and
    left NULL otherwise. A wrong mark weight would corrupt the very analytics this
    table exists for, and NULL is honest where a guess is not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Q.1 / Q1 / Q. 2 / Q.No.1: / Q. No. 3 / Question 4
# The "No." form is not cosmetic: BNSS and Labour papers use "Q.No.1:" throughout, and
# a pattern that only matched "Q.1" silently parsed zero questions from them.
MAIN_Q_RE = re.compile(r"Q(?:uestion)?\s*[.\-:]?\s*(?:No\.?\s*)?(\d+)", re.IGNORECASE)

# Some papers (both Labour Law II papers) number questions with no "Q" prefix at all:
# "1. Answer the following in not more than two sentences (Any Six)". Used only as a
# fallback, and gated on a question verb, because a bare "1." is far too common in
# statutory quotations and dates to split on unconditionally.
BARE_Q_RE = re.compile(
    r"(?:(?<=\s)|^)([1-8])[.)]\s+(?=(?:Answer|Explain|Write|Discuss|Solve|Define|"
    r"Attempt|Describe|State|Comment|Draft|Elaborate)\b)",
    re.IGNORECASE,
)

# Sub-parts: "a.", "(a)", "b)" at a plausible boundary
SUB_Q_RE = re.compile(r"(?:(?<=\s)|^)\(?([a-h])[.)]\s+")

# A marks hint in brackets, e.g. "(15)". Only 2-20 is credible for a 75-mark paper.
MARKS_RE = re.compile(r"\((\d{1,2})\)")

# OCR debris: runs of isolated punctuation/symbols and 1-2 char noise tokens.
_NOISE_RE = re.compile(r"(?:(?<=\s)|^)[^\w(]{1,3}(?=\s|$)")
_REPEAT_PUNCT_RE = re.compile(r"[.\-_~^*=:;,]{2,}")


@dataclass
class ParsedQuestion:
    question_no: str
    question_text: str
    marks: int | None


def clean_ocr(text: str) -> str:
    """Strip OCR debris without altering real words."""
    text = _REPEAT_PUNCT_RE.sub(" ", text)
    text = _NOISE_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text)
    # Drop page furniture.
    text = re.sub(r"Page\s*\d+\s*of\s*\d+", " ", text, flags=re.I)
    text = re.sub(r"Paper\s*/\s*subject\s*code[^A-Za-z]*", " ", text, flags=re.I)
    return text.strip()


def _credible_marks(segment: str) -> int | None:
    for m in MARKS_RE.finditer(segment):
        value = int(m.group(1))
        if 2 <= value <= 20:
            return value
    return None


def parse_paper(text: str) -> list[ParsedQuestion]:
    """Split a paper into questions, one row per sub-part where sub-parts exist."""
    text = clean_ocr(text)
    mains = list(MAIN_Q_RE.finditer(text))
    if len(mains) < 2:
        # Fall back to bare numbering, keeping whichever scheme found more questions.
        bare = list(BARE_Q_RE.finditer(text))
        if len(bare) > len(mains):
            mains = bare
    if not mains:
        return []

    out: list[ParsedQuestion] = []
    seen: set[str] = set()

    for i, match in enumerate(mains):
        number = match.group(1)
        start = match.end()
        end = mains[i + 1].start() if i + 1 < len(mains) else len(text)
        body = text[start:end].strip()
        if not body:
            continue

        marks = _credible_marks(body)

        subs = list(SUB_Q_RE.finditer(body))
        if len(subs) >= 2:
            for j, sub in enumerate(subs):
                s_start = sub.end()
                s_end = subs[j + 1].start() if j + 1 < len(subs) else len(body)
                sub_text = body[s_start:s_end].strip()
                if len(sub_text) < 15:
                    continue
                qno = f"{number}{sub.group(1)}"
                if qno in seen:
                    continue
                seen.add(qno)
                out.append(ParsedQuestion(qno, sub_text, marks))
        else:
            # No sub-parts: Q.1-style papers list many bare questions. Split on "?".
            parts = [p.strip() for p in re.split(r"(?<=\?)\s+", body) if len(p.strip()) > 15]
            if len(parts) > 1:
                for k, part in enumerate(parts, start=1):
                    qno = f"{number}.{k}"
                    if qno in seen:
                        continue
                    seen.add(qno)
                    out.append(ParsedQuestion(qno, part, marks))
            elif len(body) >= 15:
                if number not in seen:
                    seen.add(number)
                    out.append(ParsedQuestion(number, body, marks))

    return out


_MONTHS = ("January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December")


def parse_exam_label(title: str) -> tuple[int | None, str | None]:
    """'2026 April Cpc 75 25' -> (2026, 'April 2026')."""
    year_match = re.search(r"(20\d{2})", title)
    year = int(year_match.group(1)) if year_match else None

    month = None
    for name in _MONTHS:
        if re.search(name[:3], title, re.I):
            month = name
            break
    exam = f"{month} {year}" if month and year else (str(year) if year else None)
    return year, exam
