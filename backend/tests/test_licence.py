"""The licence gate is a legal control, not a nicety. These tests are the control."""

from backend.app.licence import (
    is_full_text_servable,
    max_chars,
    serve_chunk,
    serve_text,
)

LONG = "word " * 500  # ~2500 chars


def test_public_sources_serve_in_full():
    for lic in ("public", "govt-public"):
        assert is_full_text_servable(lic)
        text, truncated = serve_text(LONG, lic)
        assert text == LONG
        assert truncated is False


def test_owned_licensed_capped_at_200_chars():
    text, truncated = serve_text(LONG, "owned-licensed")
    assert truncated is True
    assert len(text) <= 201  # 200 + the ellipsis


def test_excerpt_only_capped_at_50_chars():
    text, truncated = serve_text(LONG, "excerpt-only")
    assert truncated is True
    assert len(text) <= 51


def test_unknown_licence_fails_closed():
    """An unrecognised licence must serve LESS, never more.

    If someone adds a licence value to the YAML and forgets the Python side, the
    failure mode must be an over-truncated excerpt, not republishing a textbook.
    """
    assert max_chars("some-new-licence") == 50
    assert is_full_text_servable("some-new-licence") is False
    text, truncated = serve_text(LONG, "some-new-licence")
    assert truncated is True
    assert len(text) <= 51


def test_short_text_under_cap_is_untouched():
    text, truncated = serve_text("Section 11 bars re-litigation.", "owned-licensed")
    assert truncated is False
    assert text == "Section 11 bars re-litigation."


def test_truncation_prefers_word_boundary():
    text, _ = serve_text(LONG, "owned-licensed")
    assert not text.rstrip("…").endswith("wor")


def test_serve_chunk_carries_citation_even_when_truncated():
    served = serve_chunk(
        chunk_id=7,
        text=LONG,
        licence="owned-licensed",
        citation="Takwani, Civil Procedure, p. 412",
    )
    assert served.truncated is True
    assert served.citation == "Takwani, Civil Procedure, p. 412"
    assert served.chunk_id == 7
    assert len(served.text) <= 201
