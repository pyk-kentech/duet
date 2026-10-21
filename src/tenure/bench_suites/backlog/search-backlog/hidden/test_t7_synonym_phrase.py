"""FX-107: 동의어가 구절·강조·스니펫에서도, FX-101·FX-102 와 함께 동작한다."""

import os
import subprocess
import sys

import pytest

from findex import Index


def ids(idx, q):
    return sorted(idx.search(q, per_page=100).ids())


def scores(idx, q):
    return {h.doc_id: h.score for h in idx.search(q, per_page=100).hits}


def cli(tmp_path, *args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "findex", "--index", str(tmp_path / "i.json"), *args],
                          capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(tmp_path))


def test_phrase_slot_is_expanded():
    i = Index()
    a = i.add("Fast automobile")
    b = i.add("fast car")
    i.add("automobile fast")
    i.add_synonyms("car", "automobile")
    assert ids(i, '"fast car"') == [a, b]
    assert ids(i, '"fast automobile"') == [a, b]


def test_phrase_middle_slot():
    i = Index()
    a = i.add("x", body="red auto wash")
    b = i.add("y", body="red car wash")
    i.add("z", body="red auto and car wash")
    i.add_synonyms("car", "auto")
    assert ids(i, '"red car wash"') == [a, b]


def test_field_phrase_and_punctuation_phrase():
    i = Index()
    a = i.add("Fast automobile", body="slow")
    b = i.add("slow", body="fast automobile")
    i.add_synonyms("car", "automobile")
    assert ids(i, 'title:"fast car"') == [a]
    assert ids(i, "fast.car") == [a, b]


def test_phrase_tf_counts_any_combination():
    syn = Index()
    syn.add("t", body="fast car fast automobile")
    syn.add("u", body="fast car other words")
    syn.add_synonyms("car", "automobile")
    plain = Index()
    plain.add("t", body="fast car fast car")
    plain.add("u", body="fast car other words")
    s, p = scores(syn, '"fast car"'), scores(plain, '"fast car"')
    assert s == pytest.approx(p, rel=1e-9)
    assert s[1] > s[2]


def test_highlight_and_snippet_mark_synonyms():
    i = Index()
    d = i.add("Fast automobile and car", body="An auto is a car.")
    i.add_synonyms("car", "automobile", "auto")
    assert i.highlight(d, "car") == "Fast [automobile] and [car]"
    assert i.snippet(d, "car") == "An [auto] is a [car]."


def test_phrase_words_and_synonyms_highlighted_separately():
    i = Index()
    d = i.add("Fast automobile, slow car")
    i.add_synonyms("car", "automobile")
    assert i.highlight(d, '"fast car"') == "[Fast] [automobile], slow [car]"


def test_prefix_highlight_not_expanded():
    i = Index()
    d = i.add("automobile car")
    i.add_synonyms("car", "automobile")
    assert i.highlight(d, "car*") == "automobile [car]"
    assert i.highlight(d, "car") == "[automobile] [car]"


def test_accented_synonyms():
    i = Index()
    a = i.add("Coffeehouse guide")
    b = i.add("Le Café")
    i.add_synonyms("café", "coffeehouse")
    assert ids(i, "cafe") == [a, b]
    assert ids(i, "COFFEEHOUSE") == [a, b]
    assert i.highlight(a, "café") == "[Coffeehouse] guide"
    assert i.highlight(b, "coffeehouse") == "Le [Café]"


def test_hyphenated_synonym():
    i = Index()
    a = i.add("Send an e-mail")
    b = i.add("New message")
    c = i.add("email me")
    i.add_synonyms("e-mail", "message")
    assert i.synonyms() == [["e-mail", "message"]]
    assert ids(i, "message") == [a, b, c]
    assert i.highlight(a, "message") == "Send an [e-mail]"
    assert ids(i, '"new email"') == [b]


def test_negated_phrase_with_synonyms():
    i = Index()
    i.add("fast automobile")
    b = i.add("fast bike")
    i.add_synonyms("car", "automobile")
    assert ids(i, 'fast -"fast car"') == [b]


def test_cli_snippets_highlight_synonyms(tmp_path):
    cli(tmp_path, "add", "Car dealer", "--body", "used automobile sales")
    cli(tmp_path, "synonyms", "add", "car", "automobile")
    lines = cli(tmp_path, "search", "car", "--snippets").stdout.splitlines()
    assert lines[0] == "검색 결과 1건" and lines[2] == "    used [automobile] sales"
