import pytest

from findex.analyzer import Analyzer, Term
from findex.stemmer import stem
from findex.textutil import normalize


def test_stopwords_removed_and_positions_consecutive():
    a = Analyzer()
    assert a.analyze("The Lord of the Rings") == [Term("lord", 0), Term("ring", 1)]


def test_custom_stopwords_replace_default():
    a = Analyzer(stopwords=["lord"])
    assert a.query_terms("the lord rings") == ["the", "ring"]


def test_empty_stopwords():
    assert Analyzer(stopwords=[]).query_terms("the end") == ["the", "end"]


def test_stopwords_string_rejected():
    with pytest.raises(ValueError):
        Analyzer(stopwords="the")


@pytest.mark.parametrize("word,expected", [
    ("cats", "cat"), ("running", "run"), ("studies", "study"), ("classes", "class"),
    ("status", "status"), ("analysis", "analysis"), ("quickly", "quick"), ("stopped", "stop"),
    ("news", "news"), ("children", "child"),
])
def test_stem_table(word, expected):
    assert stem(word) == expected


def test_stem_skips_short_and_non_alpha():
    assert stem("bus") == "bus"
    assert stem("mp3s") == "mp3s"


def test_stem_off():
    assert Analyzer(stem=False).query_terms("Running cats") == ["running", "cats"]


def test_normalize_casefold():
    assert normalize("Straße") == "strasse"
    assert normalize("HELLO") == "hello"


def test_settings_roundtrip():
    a = Analyzer(stopwords=["x", "y"], stem=False)
    b = Analyzer.from_settings(a.settings())
    assert b.stopwords == a.stopwords and b.stem is False
    assert Analyzer.from_settings(Analyzer().settings()).custom_stopwords is None
