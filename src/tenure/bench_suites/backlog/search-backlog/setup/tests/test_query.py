from datetime import date

import pytest

from findex import QuerySyntaxError
from findex.query import AndQ, DateQ, NotQ, OrQ, PhraseQ, PrefixQ, TagQ, TermQ, parse


def test_precedence():
    assert parse("a OR b c") == OrQ((TermQ("a"), AndQ((TermQ("b"), TermQ("c")))))


def test_not_keyword():
    assert parse("a NOT b") == AndQ((TermQ("a"), NotQ(TermQ("b"))))


def test_phrase_and_field_phrase():
    assert parse('"big cat" title:"small dog"') == AndQ((PhraseQ("big cat"), PhraseQ("small dog", "title")))


def test_fields_and_filters():
    assert parse("title:x tag:y") == AndQ((TermQ("x", "title"), TagQ("y")))
    assert parse("date:2024-02") == DateQ(date(2024, 2, 1), date(2024, 2, 29))


def test_prefix():
    assert parse("Pyth*") == PrefixQ("pyth")
    with pytest.raises(QuerySyntaxError):
        parse("p*")


@pytest.mark.parametrize("q", ['"open', "(a b", "a b)", "()", "a OR", "NOT"])
def test_syntax_errors(q):
    with pytest.raises(QuerySyntaxError):
        parse(q)


def test_empty_query():
    assert parse("   ") is None
