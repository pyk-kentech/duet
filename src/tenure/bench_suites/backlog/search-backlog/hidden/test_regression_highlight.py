"""기존 동작 (README "강조와 스니펫" 절)."""

import pytest

from findex import Index


def test_phrase_words_highlighted_separately():
    i = Index()
    d = i.add("Rings of the Lord, and a lord ring", body="lord here; rings there")
    assert i.highlight(d, '"lord rings"') == "[Rings] of the [Lord], and a [lord] [ring]"
    assert i.snippet(d, '"lord rings"') == "[lord] here; [rings] there"


def test_not_tag_date_not_highlighted():
    i = Index()
    d = i.add("Cats and dogs", tags=["cats"], date="2024-01-01")
    assert i.highlight(d, "cats -dogs") == "[Cats] and dogs"
    assert i.highlight(d, "tag:cats date:2024") == "Cats and dogs"
    assert i.highlight(d, "cats NOT (dogs OR birds)") == "[Cats] and dogs"


def test_field_restricted_terms():
    i = Index()
    d = i.add("apple title", body="apple body")
    assert i.highlight(d, "title:apple") == "[apple] title"
    assert i.snippet(d, "title:apple") == "apple body"
    assert i.snippet(d, "body:apple") == "[apple] body"
    assert i.highlight(d, "body:apple") == "apple title"


def test_stopwords_not_highlighted_and_case_kept():
    i = Index()
    d = i.add("The CAT in the Hat")
    assert i.highlight(d, "the cat") == "The [CAT] in the Hat"
    assert i.highlight(d, '"cat in the hat"') == "The [CAT] in the [Hat]"


def test_prefix_and_stem_highlight():
    i = Index()
    d = i.add("Programming in Python", body="programmers program programs")
    assert i.highlight(d, "pyth*") == "Programming in [Python]"
    assert i.snippet(d, "programs") == "programmers [program] [programs]"
    assert i.snippet(d, "prog*") == "[programmers] [program] [programs]"


def test_snippet_window_rules():
    i = Index()
    words = " ".join(f"w{n:02d}" for n in range(40))            # 4 chars each + spaces
    d = i.add("t", body=words + " target end")
    s = i.snippet(d, "target", length=40)
    assert s.startswith("…") and "[target]" in s and s.endswith("end")
    inner = s[1:].replace("[", "").replace("]", "")
    assert len(inner) <= 40 and inner.split()[0] in words.split()
    s2 = i.snippet(d, "nothing", length=40)
    assert s2 == "w00 w01 w02 w03 w04 w05 w06 w07 w08 w09…"


def test_snippet_squeezes_whitespace_and_custom_markers():
    i = Index()
    d = i.add("t", body="first line\n\nsecond   line")
    assert i.snippet(d, "second", markers=("<b>", "</b>")) == "first line <b>second</b> line"
    with pytest.raises(ValueError):
        i.snippet(d, "x", markers=("<b>",))
    with pytest.raises(ValueError):
        i.highlight(d, "x", field="tags")
