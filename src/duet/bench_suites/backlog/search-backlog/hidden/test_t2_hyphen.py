"""FX-102: 하이픈 단어는 조각과 합친 형태로 색인, 검색어에서는 합친 형태 하나."""

import math
import os
import subprocess
import sys

import pytest

from findex import Index


def ids(idx, q):
    return sorted(idx.search(q, per_page=100).ids())


def score_of(idx, q, doc_id):
    return {h.doc_id: h.score for h in idx.search(q, per_page=100).hits}[doc_id]


def cli(tmp_path, *args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "findex", "--index", str(tmp_path / "i.json"), *args],
                          capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(tmp_path))


def test_found_by_joined_parts_and_hyphenated_query():
    i = Index()
    a = i.add("Contact", body="Send an e-mail today")
    assert ids(i, "email") == [a]
    assert ids(i, "mail") == [a]
    assert ids(i, "e-mail") == [a]


def test_hyphenated_query_is_the_joined_form():
    i = Index()
    a = i.add("x", body="email marketing")
    i.add("y", body="e mail separately")
    assert ids(i, "e-mail") == [a]


def test_multi_hyphen_with_stopword_parts():
    i = Index()
    a = i.add("State-of-the-art search")
    assert ids(i, "stateoftheart") == [a]
    assert ids(i, "state-of-the-art") == [a]
    assert ids(i, "state") == [a] and ids(i, "art") == [a]
    assert ids(i, '"state art search"') == [a]


def test_stemming_on_joined_and_parts():
    i = Index()
    a = i.add("x", body="many e-mails")
    assert ids(i, "email") == [a]
    assert ids(i, "mails") == [a]
    assert ids(i, "e-mails") == [a]


def test_digits_in_hyphen_words():
    i = Index()
    a = i.add("covid-19 update")
    assert ids(i, "covid19") == [a]
    assert ids(i, "covid") == [a]
    assert ids(i, "19") == [a]


def test_only_single_inner_hyphens_join():
    i = Index()
    a = i.add("x--y zed")
    b = i.add("-flag pre- fix")
    c = i.add("well-known fact")
    assert ids(i, "wellknown") == [c]
    assert ids(i, "xy") == []
    assert ids(i, "x") == [a]
    assert ids(i, "flag") == [b]
    assert ids(i, "prefix") == []


def test_phrase_positions_around_hyphen_word():
    i = Index()
    a = i.add("x", body="send e-mail address now")
    b = i.add("y", body="send e mail")
    for q in ['"send email"', '"e-mail address"', '"mail address"', '"send e-mail address"']:
        assert ids(i, q) == [a], q
    assert ids(i, '"e mail"') == [a, b]
    assert ids(i, '"send e-mail"') == [a, b]          # hyphen word inside a phrase = its parts
    assert ids(i, '"send address"') == []


def test_field_length_counts_parts_only():
    i = Index()
    a = i.add("one", body="e-mail now")
    i.add("two", body="plain text")
    # N = 2, df(email) = 1, body lengths 3 and 2 (the joined form is not counted)
    idf = math.log(1 + (2 - 1 + 0.5) / (1 + 0.5))
    expected = idf * 1 * 2.2 / (1 + 1.2 * (1 - 0.75 + 0.75 * 3 / 2.5))
    assert score_of(i, "email", a) == pytest.approx(expected, rel=1e-9)


def test_same_score_for_hyphenated_and_spaced():
    i = Index()
    a = i.add("t1", body="e-mail")
    b = i.add("t2", body="e mail")
    i.add("t3", body="other words here")
    assert ids(i, "email") == [a]
    assert score_of(i, "mail", a) == pytest.approx(score_of(i, "mail", b), rel=1e-12)


def test_not_shorthand_still_works():
    i = Index()
    a = i.add("x", body="e-mail list")
    b = i.add("y", body="e list")
    c = i.add("z", body="mail list")
    d = i.add("w", body="email list")
    assert ids(i, "list -mail") == [b, d]
    assert ids(i, "e -mail") == [b]
    assert ids(i, "list -e-mail") == [b, c]
    assert a not in ids(i, "list NOT email")


def test_field_query_with_hyphen():
    i = Index()
    a = i.add("X-Ray Vision")
    b = i.add("xray", body="nothing")
    c = i.add("other", body="x-ray in body")
    assert ids(i, "title:x-ray") == [a, b]
    assert ids(i, "x-ray") == [a, b, c]


def test_highlight_joined_versus_fragment():
    i = Index()
    d = i.add("Send e-mail now", body="An e-mail, a mail and an email.")
    assert i.highlight(d, "email") == "Send [e-mail] now"
    assert i.highlight(d, "e-mail") == "Send [e-mail] now"
    assert i.highlight(d, "mail") == "Send e-[mail] now"
    assert i.highlight(d, "email mail") == "Send [e-mail] now"
    assert i.snippet(d, "email") == "An [e-mail], a mail and an [email]."
    assert i.snippet(d, "mail") == "An e-[mail], a [mail] and an email."


def test_prefix_and_suggest_see_joined_form():
    i = Index()
    a = i.add("x", body="e-mail")
    assert ids(i, "ema*") == [a]
    assert i.suggest("ema") == [("email", 1)]


def test_other_punctuation_unchanged():
    i = Index()
    a = i.add("x", body="foo.bar baz")
    i.add("y", body="bar foo")
    c = i.add("z", body="well-being")
    assert ids(i, "foo.bar") == [a]
    assert ids(i, "foobar") == []
    assert ids(i, "wellbeing") == [c]


def test_cli_hyphen(tmp_path):
    cli(tmp_path, "add", "E-Mail tips", "--body", "write a good e-mail")
    cli(tmp_path, "add", "Email basics")
    r = cli(tmp_path, "search", "e-mail", "--snippets")
    lines = r.stdout.splitlines()
    assert lines[0] == "검색 결과 2건"
    assert "    write a good [e-mail]" in lines
