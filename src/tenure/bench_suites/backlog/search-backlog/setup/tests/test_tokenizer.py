from findex.tokenizer import Token, tokenize, words


def test_simple_words_and_offsets():
    toks = tokenize("Hello, world!")
    assert toks == [Token("Hello", 0, 5), Token("world", 7, 12)]


def test_apostrophe_between_letters_joins():
    assert words("don't stop") == ["dont", "stop"]
    assert words("O’Brien") == ["OBrien"]


def test_apostrophe_not_between_letters_splits():
    assert words("'quoted' rock'") == ["quoted", "rock"]


def test_decimal_point_between_digits():
    assert words("pi is 3.14, v1.2 ok.") == ["pi", "is", "3.14", "v1.2", "ok"]


def test_korean_words():
    assert words("한국어 검색 엔진입니다.") == ["한국어", "검색", "엔진입니다"]


def test_underscore_is_word_char():
    assert words("snake_case value") == ["snake_case", "value"]


def test_punctuation_splits():
    assert words("foo.bar x/y a+b") == ["foo", "bar", "x", "y", "a", "b"]
