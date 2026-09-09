"""Act parsing. If this drifts, every section-level answer silently degrades."""

from ingest.parse_act import parse

# Shaped like a real bare act: TOC, enacting formula, then sections.
SAMPLE = """
THE SAMPLE PROCEDURE CODE, 1908

ARRANGEMENT OF SECTIONS

1. Short title.
9. Courts to try all civil suits.
11. Res judicata.
41A. Notice of appearance.

BE it enacted by Parliament as follows:—

1. Short title and commencement.—This Act may be called the Sample Procedure Code, 1908.
It shall come into force on the first day of January, 1909.

9. Courts to try all civil suits unless barred.—The Courts shall, subject to the
provisions herein contained, have jurisdiction to try all suits of a civil nature.

11. Res judicata.—No Court shall try any suit or issue in which the matter directly and
substantially in issue has been directly and substantially in issue in a former suit
between the same parties.

41A. Notice of appearance before police officer.—The police officer shall, in all cases
where the arrest of a person is not required, issue a notice directing the person to
appear before him.
"""


def test_finds_all_sections_and_skips_the_table_of_contents():
    provisions = parse(SAMPLE)
    numbers = [p.section_no for p in provisions]
    assert numbers == ["1", "9", "11", "41A"]


def test_lettered_sections_are_kept_distinct():
    """41A is a different section from 41 and must not be collapsed into it."""
    provisions = parse(SAMPLE)
    assert "41A" in [p.section_no for p in provisions]


def test_marginal_note_is_split_from_operative_text():
    provisions = parse(SAMPLE)
    res_judicata = next(p for p in provisions if p.section_no == "11")
    assert res_judicata.marginal_note == "Res judicata"
    assert res_judicata.text.startswith("No Court shall try any suit")
    # The marginal note must not be duplicated into the body.
    assert "Res judicata.—" not in res_judicata.text


def test_operative_text_is_verbatim():
    """Statutory text is served verbatim; the parser must not reflow or trim it."""
    provisions = parse(SAMPLE)
    section_9 = next(p for p in provisions if p.section_no == "9")
    assert "jurisdiction to try all suits of a civil nature" in section_9.text


def test_table_of_contents_entries_produce_no_empty_provisions():
    provisions = parse(SAMPLE)
    assert all(len(p.text) >= 20 for p in provisions)


def test_ordering_is_document_order():
    provisions = parse(SAMPLE)
    assert [p.ord for p in provisions] == [0, 1, 2, 3]
