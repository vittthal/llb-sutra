"""Chunking. The rule that matters: never split a statutory section."""

from ingest.chunk import chunk_document, chunk_provision, estimate_tokens


def test_provision_chunk_leads_with_the_section_number():
    """Lexical search must hit "Section 11" — so it has to be in the chunk text."""
    c = chunk_provision("11", "Res judicata", "No Court shall try any suit...", 0)
    assert c.text.startswith("Section 11. Res judicata")
    assert c.heading == "Section 11. Res judicata"


def test_provision_chunk_without_marginal_note():
    c = chunk_provision("41A", None, "The police officer shall...", 3)
    assert c.heading == "Section 41A"
    assert c.ord == 3


def test_judgment_splits_on_numbered_paragraphs():
    judgment = (
        "1. This appeal arises out of a decree.\n\n"
        "2. The appellant contends that the suit was barred.\n\n"
        "3. We are unable to accept that contention."
    )
    chunks = chunk_document(judgment, "judgment")
    assert len(chunks) == 3
    assert chunks[1].text.startswith("2.")


def test_pyq_splits_per_question():
    paper = (
        "Q.1 Explain the doctrine of res judicata. (15 marks)\n\n"
        "Q.2 Discuss the essentials of a valid decree. (10 marks)\n\n"
        "Q.3 Write short notes. (5 marks)"
    )
    chunks = chunk_document(paper, "pyq")
    assert len(chunks) == 3


def test_oversized_part_is_emitted_whole_not_cut():
    """A single long section is kept intact even though it exceeds the target."""
    huge = "word " * 2000
    chunks = chunk_document(huge, "notes")
    assert len(chunks) == 1
    assert chunks[0].text.strip() == huge.strip()


def test_notes_are_packed_towards_the_target_size():
    # All-caps headings only — the heading regex matches letters and punctuation,
    # not digits, so "HEADING 1" would not register as a heading.
    names = ["ALPHA", "BRAVO", "CHARLIE", "DELTA", "ECHO", "FOXTROT", "GOLF", "HOTEL"]
    body = "\n\n".join(f"HEADING {n}\n" + ("word " * 120) for n in names)
    chunks = chunk_document(body, "notes")
    assert len(chunks) > 1
    # Packing should not produce single-sentence fragments.
    assert all(c.n_tokens > 50 for c in chunks)


def test_empty_document_produces_no_chunks():
    assert chunk_document("   \n\n  ", "notes") == []


def test_token_estimate_is_monotonic():
    assert estimate_tokens("one two three") < estimate_tokens("one two three four five six")
