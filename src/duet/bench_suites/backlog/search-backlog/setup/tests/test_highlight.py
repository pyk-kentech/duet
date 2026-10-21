import pytest

from findex import Index


@pytest.fixture
def idx():
    i = Index()
    i.add("Running with Python", body="Python runners run fast. " * 2)
    i.add("Long", body=" ".join(f"word{n}" for n in range(60)) + " target here")
    return i


def test_highlight_title_with_stemming(idx):
    assert idx.highlight(1, "run") == "[Running] with Python"


def test_custom_markers(idx):
    assert idx.highlight(1, "python", markers=("<b>", "</b>")) == "Running with <b>Python</b>"


def test_snippet_short_body_whole(idx):
    assert idx.snippet(1, "python") == "[Python] runners run fast. [Python] runners run fast."


def test_prefix_highlight(idx):
    assert idx.highlight(1, "pyth*") == "Running with [Python]"


def test_snippet_without_match_starts_at_beginning(idx):
    s = idx.snippet(2, "nothing")
    assert s.startswith("word0 word1") and s.endswith("…")
    assert len(s) <= 121


def test_snippet_bad_length(idx):
    with pytest.raises(ValueError):
        idx.snippet(1, "python", length=5)
