import pytest

from deepmerge import merge, merge_all, parse_overrides


def test_recursive_merge_and_override_wins():
    base = {"a": 1, "srv": {"host": "x", "port": 1}, "keep": True}
    over = {"srv": {"port": 2, "tls": False}, "a": "s"}
    assert merge(base, over) == {"a": "s", "srv": {"host": "x", "port": 2, "tls": False}, "keep": True}


def test_lists_replaced_not_concatenated():
    assert merge({"l": [1, 2], "m": {"l": [3]}}, {"l": [9], "m": {"l": []}}) == {"l": [9], "m": {"l": []}}


def test_type_mismatch_override_wins():
    assert merge({"a": {"b": 1}}, {"a": 5}) == {"a": 5}
    assert merge({"a": 5}, {"a": {"b": 1}}) == {"a": {"b": 1}}
    assert merge({"a": [1]}, {"a": {"b": 1}}) == {"a": {"b": 1}}


def test_none_deletes_key_nested():
    base = {"a": 1, "n": {"x": 1, "y": 2}}
    assert merge(base, {"a": None, "n": {"y": None}, "zz": None}) == {"n": {"x": 1}}


def test_key_order():
    r = merge({"b": 1, "a": 2, "c": 3}, {"d": 4, "a": 0, "e": 5})
    assert list(r) == ["b", "a", "c", "d", "e"]
    r = merge({"n": {"q": 1, "p": 2}}, {"n": {"r": 3, "q": 0}})
    assert list(r["n"]) == ["q", "p", "r"]


def test_inputs_not_mutated_and_not_shared():
    base = {"n": {"l": [1, {"deep": 1}]}, "only_base": {"x": [1]}}
    over = {"n": {"k": 1}, "only_over": {"y": [2]}}
    r = merge(base, over)
    r["n"]["l"][1]["deep"] = 99
    r["n"]["l"].append(3)
    r["only_base"]["x"].append(2)
    r["only_over"]["y"].append(3)
    assert base == {"n": {"l": [1, {"deep": 1}]}, "only_base": {"x": [1]}}
    assert over == {"n": {"k": 1}, "only_over": {"y": [2]}}


def test_type_error():
    with pytest.raises(TypeError):
        merge([], {})
    with pytest.raises(TypeError):
        merge({}, "x")


def test_merge_all():
    assert merge_all() == {}
    one = {"a": {"b": [1]}}
    r = merge_all(one)
    assert r == one and r is not one and r["a"]["b"] is not one["a"]["b"]
    assert merge_all({"a": 1}, {"b": 2}, {"a": None, "c": {"d": 1}}, {"c": {"e": 2}}) == {"b": 2, "c": {"d": 1, "e": 2}}


def test_parse_overrides_values():
    r = parse_overrides(["server.port=8080", "debug=true", "name=api", "tags=[1, 2]", "q=\"x=y\"",
                         "rm=null", "ratio=0.5", "path=a=b"])
    assert r == {"server": {"port": 8080}, "debug": True, "name": "api", "tags": [1, 2], "q": "x=y",
                 "rm": None, "ratio": 0.5, "path": "a=b"}


def test_parse_overrides_nested_and_last_wins():
    assert parse_overrides(["a.b.c=1", "a.b.d=2", "a.b.c=3"]) == {"a": {"b": {"c": 3, "d": 2}}}
    assert parse_overrides([]) == {}


@pytest.mark.parametrize("bad", ["noequals", "=1", "a..b=1", ".a=1", "a.=1"])
def test_parse_overrides_errors(bad):
    with pytest.raises(ValueError):
        parse_overrides([bad])


def test_overrides_feed_merge():
    base = {"server": {"port": 80, "host": "h"}, "debug": False}
    assert merge(base, parse_overrides(["server.port=8080", "debug=null"])) == {"server": {"port": 8080, "host": "h"}}
