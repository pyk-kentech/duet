"""기존 동작 (README "검색어" 절): 고치는 동안 깨지기 쉬운 것들."""

import pytest

from findex import Index, QuerySyntaxError


def ids(idx, q):
    return sorted(idx.search(q, per_page=100).ids())


@pytest.fixture
def idx():
    i = Index()
    i.add("Cat food", body="dry food for cats", tags=["pets"], date="2024-01-15")        # 1
    i.add("Dog food", body="wet food for dogs", tags=["pets"], date="2024-02-10")        # 2
    i.add("Cat and dog", body="living together", tags=["Machine Learning"], date="2024-02-29")  # 3
    i.add("Bird seed", body="seeds for birds draft", date="2023-12-31")                   # 4
    i.add("Lord of the Rings", body="a long journey")                                     # 5
    return i


def test_dash_prefix_is_not(idx):
    assert ids(idx, "food -cat") == [2]
    assert ids(idx, 'food -"dog food"') == [1]
    assert ids(idx, "-tag:pets cat") == [3]
    assert ids(idx, "food - cat") == [1]          # a lone '-' is ignored


def test_lowercase_operators_are_words(idx):
    assert ids(idx, "cat or dog") == [3]          # 'or' is a stopword: cat AND dog
    assert ids(idx, "cat OR dog") == [1, 2, 3]
    assert ids(idx, "cat not dog") == [3]
    assert ids(idx, "cat NOT dog") == [1]


def test_precedence_not_and_or(idx):
    assert ids(idx, "bird OR cat dog") == [3, 4]
    assert ids(idx, "(bird OR cat) food") == [1]
    assert ids(idx, "NOT cat food") == [2]


def test_phrase_ignores_stopword_positions(idx):
    i = idx
    j = i.add("Lord Rings", body="x")
    k = i.add("Lord of Rings", body="y")
    assert ids(i, '"lord of the rings"') == [5, j, k]
    assert ids(i, '"lord rings"') == [5, j, k]
    assert ids(i, '"rings lord"') == []


def test_punctuated_word_is_a_phrase():
    i = Index()
    a = i.add("x", body="foo bar baz")
    i.add("y", body="bar foo")
    c = i.add("z", body="see x/y axis")
    assert ids(i, "foo.bar") == [a]
    assert ids(i, "x/y") == [c]


def test_unknown_field_is_a_plain_word():
    i = Index()
    a = i.add("x", body="foo bar")
    assert ids(i, "foo:bar") == [a]
    assert ids(i, "Title:foo") == []        # field names are lowercase only -> phrase "title foo"


def test_prefix_rules(idx):
    assert ids(idx, "CAT*") == [1, 3]
    assert ids(idx, "title:see*") == [4]
    with pytest.raises(QuerySyntaxError):
        idx.search("c*")


def test_prefix_matches_index_terms_not_raw_words():
    i = Index()
    a = i.add("x", body="jumped running")
    assert ids(i, "jump*") == [a]
    assert ids(i, "jumpe*") == []           # the index holds the stem 'jump'
    assert ids(i, "runn*") == []


def test_stopword_only_and_empty_queries(idx):
    assert idx.search("the of and").total == 0
    assert idx.search("").total == 0
    assert ids(idx, "the cat") == [1, 3]


def test_not_only_query(idx):
    res = idx.search("-food")
    assert res.ids() == [3, 4, 5]
    assert all(h.score == 0.0 for h in res.hits)


def test_date_ranges(idx):
    assert ids(idx, "date:2024-02") == [2, 3]
    assert ids(idx, "date:..2023") == [4]
    assert ids(idx, "date:2024-01-15..2024-02-10") == [1, 2]
    assert ids(idx, "date:2024..") == [1, 2, 3]
    assert ids(idx, "date:2024") == [1, 2, 3]
    with pytest.raises(QuerySyntaxError):
        idx.search("date:2024-02-30")
    with pytest.raises(QuerySyntaxError):
        idx.search("date:2024-03..2024-01")


def test_tag_filter_matches_whole_tag(idx):
    assert ids(idx, 'tag:"machine learning"') == [3]
    assert ids(idx, "tag:machine") == []
    assert ids(idx, "tag:PETS") == [1, 2]


@pytest.mark.parametrize("q", ['"open', "(a b", "a b)", "()", "AND x", "x OR"])
def test_syntax_errors(idx, q):
    with pytest.raises(QuerySyntaxError):
        idx.search(q)


def test_field_terms(idx):
    assert ids(idx, "title:food") == [1, 2]
    assert ids(idx, "body:food") == [1, 2]
    assert ids(idx, "title:seed") == [4]
    assert ids(idx, "body:together") == [3]
    assert ids(idx, "title:together") == []


def test_tokens_numbers_apostrophes_underscores():
    i = Index()
    a = i.add("Pi is 3.14", body="don't panic, O’Brien")
    b = i.add("snake_case names")
    assert ids(i, "3.14") == [a]
    assert ids(i, "14") == []
    assert ids(i, "dont") == [a] and ids(i, "don't") == [a]
    assert ids(i, "obrien") == [a]
    assert ids(i, "snake_case") == [b]
    assert ids(i, "snake") == []
