"""FX-104: 동의어 묶음 (등록·합치기·검색 확장·점수·CLI)."""

import os
import subprocess
import sys

import pytest

from findex import Index


def corpus():
    i = Index()
    i.add("Car dealer", body="new and used cars")             # 1
    i.add("Automobile history", body="the first automobiles")  # 2
    i.add("Auto repair", body="fix your engine")               # 3
    i.add("Bicycle shop", body="bikes and parts")              # 4
    i.add("Car or auto", body="an automobile is a car")        # 5: several words of one group
    return i


def ids(idx, q):
    return sorted(idx.search(q, per_page=100).ids())


def scores(idx, q):
    return {h.doc_id: h.score for h in idx.search(q, per_page=100).hits}


def same_scores(a, b):
    assert set(a) == set(b)
    for d in a:
        assert a[d] == pytest.approx(b[d], rel=1e-9), d


def cli(tmp_path, *args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "findex", "--index", str(tmp_path / "i.json"), *args],
                          capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(tmp_path))


def test_bidirectional_expansion():
    i = corpus()
    assert i.add_synonyms("car", "automobile", "auto") is None
    assert ids(i, "car") == [1, 2, 3, 5]
    assert ids(i, "automobile") == [1, 2, 3, 5]
    assert ids(i, "auto") == [1, 2, 3, 5]
    assert ids(i, "bicycle") == [4]


def test_words_are_analyzed_like_the_index():
    i = corpus()
    i.add_synonyms("Cars", "AUTOMOBILES")
    assert ids(i, "car") == [1, 2, 5]
    assert ids(i, "automobile") == [1, 2, 5]
    assert i.synonyms() == [["Cars", "AUTOMOBILES"]]


def test_score_equals_or_without_synonyms():
    i = corpus()
    i.add_synonyms("car", "automobile", "auto")
    plain = corpus()
    same_scores(scores(i, "car"), scores(plain, "car OR automobile OR auto"))
    same_scores(scores(i, "title:auto"), scores(plain, "title:car OR title:automobile OR title:auto"))
    same_scores(scores(i, "car repair"), scores(plain, "(car OR automobile OR auto) repair"))


def test_not_is_expanded():
    i = Index()
    i.add("Vehicle tax", body="car owners")
    i.add("Vehicle law", body="automobile rules")
    c = i.add("Vehicle list", body="trucks")
    i.add_synonyms("car", "automobile")
    assert ids(i, "vehicle -car") == [c]
    assert ids(i, "vehicle NOT automobile") == [c]


def test_prefix_and_tag_are_not_expanded():
    i = Index()
    a = i.add("Automobile", tags=["automobile"])
    b = i.add("car parts", tags=["car"])
    i.add_synonyms("car", "automobile")
    assert ids(i, "car") == [a, b]
    assert ids(i, "car*") == [b]
    assert ids(i, "tag:car") == [b]


def test_registration_order_does_not_matter():
    i = Index()
    i.add_synonyms("car", "auto")
    a = i.add("auto shop")
    b = i.add("car wash")
    assert ids(i, "car") == [a, b]


def test_merge_with_one_group():
    i = Index()
    i.add_synonyms("car", "auto")
    i.add_synonyms("bike", "bicycle")
    i.add_synonyms("auto", "Automobile", "cars")
    assert i.synonyms() == [["car", "auto", "Automobile"], ["bike", "bicycle"]]
    a = i.add("automobile club")
    assert ids(i, "car") == [a]


def test_merge_two_groups_keeps_first_position():
    i = Index()
    i.add_synonyms("car", "auto")
    i.add_synonyms("bike", "bicycle")
    i.add_synonyms("cycle", "moped")
    i.add_synonyms("moped", "Car")
    assert i.synonyms() == [["car", "auto", "cycle", "moped"], ["bike", "bicycle"]]
    a = i.add("cycle path")
    assert ids(i, "auto") == [a]


@pytest.mark.parametrize("words", [("car",), ("car", "Cars"), ("car", "the"), ("car", "machine learning"), ("car", "")])
def test_invalid_groups_are_rejected(words):
    i = Index()
    i.add_synonyms("bike", "bicycle")
    with pytest.raises(ValueError):
        i.add_synonyms(*words)
    assert i.synonyms() == [["bike", "bicycle"]]
    a = i.add("bike")
    i.add("car")
    assert ids(i, "bicycle") == [a]


def test_count_and_facets_follow_expansion():
    i = Index()
    i.add("car one", tags=["x"])
    i.add("auto two", tags=["y"])
    i.add("bike", tags=["x"])
    i.add_synonyms("car", "auto")
    assert i.count("car") == 2
    assert i.facets("car") == [("x", 1), ("y", 1)]


def test_cli_synonyms(tmp_path):
    cli(tmp_path, "add", "Car dealer")
    cli(tmp_path, "add", "Automobile history")
    r = cli(tmp_path, "synonyms", "add", "car", "automobile", "auto")
    assert r.returncode == 0 and r.stdout == ""
    assert cli(tmp_path, "synonyms", "list").stdout.splitlines() == ["car, automobile, auto"]
    assert cli(tmp_path, "search", "auto").stdout.splitlines()[0] == "검색 결과 2건"
    r = cli(tmp_path, "synonyms", "add", "car")
    assert r.returncode == 1 and r.stderr.startswith("오류:")
    assert cli(tmp_path, "synonyms", "list").stdout.splitlines() == ["car, automobile, auto"]
