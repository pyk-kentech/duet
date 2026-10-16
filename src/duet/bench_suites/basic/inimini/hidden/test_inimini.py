import pytest

import inimini
from inimini import ParseError, dumps, parse


def test_basic():
    assert parse("[a]\nx = 1\ny=2\n\n[b]\nz = hello world\n") == {
        "a": {"x": "1", "y": "2"}, "b": {"z": "hello world"}}


def test_global_section_only_when_present():
    assert parse("k = v\n[s]\nq = w") == {"": {"k": "v"}, "s": {"q": "w"}}
    assert "" not in parse("[s]\nq = w\n")


def test_comments_and_blank_lines():
    text = "; top\n# also\n   ; indented\n\n   \n[s]\na = 1 ; not a comment\nb = x#y\n"
    assert parse(text) == {"s": {"a": "1 ; not a comment", "b": "x#y"}}


def test_first_equals_splits():
    assert parse("[s]\nurl = a=b=c\n") == {"s": {"url": "a=b=c"}}


def test_empty_value_and_case():
    assert parse("[s]\nKey =\nkey = 2\n") == {"s": {"Key": "", "key": "2"}}


def test_duplicate_key_and_repeated_section():
    assert parse("[s]\na = 1\n[t]\nb = 2\n[s]\na = 3\nc = 4\n") == {"s": {"a": "3", "c": "4"}, "t": {"b": "2"}}


def test_section_name_stripped_and_empty_section():
    assert parse("[  spaced name ]\n[empty]\n") == {"spaced name": {}, "empty": {}}


def test_quotes():
    assert parse('[s]\na = "  padded  "\nb = ""\nc = "x\nd = say "hi" now\n') == {
        "s": {"a": "  padded  ", "b": "", "c": '"x', "d": 'say "hi" now'}}


def test_crlf():
    assert parse("[s]\r\na = 1\r\nb = 2\r\n") == {"s": {"a": "1", "b": "2"}}


@pytest.mark.parametrize("text,lineno", [
    ("[s]\njunk\n", 2),
    ("[s\na = 1\n", 1),
    ("a = 1\n[]\n", 2),
    ("\n\n[   ]\n", 3),
    ("[s]\na = 1\n= 2\n", 3),
    ("; c\n[s]\n\nnoequals\n", 4),
])
def test_errors(text, lineno):
    with pytest.raises(ParseError) as e:
        parse(text)
    assert e.value.lineno == lineno
    assert isinstance(e.value, ValueError)


def test_parse_error_is_exported():
    assert issubclass(inimini.ParseError, ValueError)


@pytest.mark.parametrize("data", [
    {},
    {"s": {"a": "1"}},
    {"": {"g": "v"}, "s": {"a": "1", "b": ""}, "t": {}},
    {"s": {"a": "  lead", "b": "trail  ", "c": '"quoted"', "d": "x = y ; z # w"}},
    {"b": {"k": "1"}, "a": {"k": "2"}},
])
def test_roundtrip(data):
    assert parse(dumps(data)) == data


def test_dumps_global_first():
    out = dumps({"s": {"a": "1"}, "": {"g": "v"}})
    assert out.index("g") < out.index("[s]")
