"""기존 동작 (README "점수"·"페이지" 절)."""

import json
import math
import os
import subprocess
import sys

import pytest

from findex import Index

K1, B = 1.2, 0.75


def bm25(tf, length, avg, n, df):
    idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
    return idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / avg))


def scores(idx, q):
    return {h.doc_id: h.score for h in idx.search(q, per_page=100).hits}


def cli(tmp_path, *args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "findex", "--index", str(tmp_path / "i.json"), *args],
                          capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(tmp_path))


def small():
    i = Index()
    i.add("apple", body="apple banana apple")          # title len 1, body len 3
    i.add("banana split", body="cherry")               # 2, 1
    i.add("cherry pie", body="apple pie recipe here")  # 2, 4
    return i


def test_exact_bm25_term():
    s = scores(small(), "apple")
    n = 3
    title_avg, body_avg = 5 / 3, 8 / 3
    exp1 = 2.0 * bm25(1, 1, title_avg, n, 1) + 1.0 * bm25(2, 3, body_avg, n, 2)
    exp3 = 1.0 * bm25(1, 4, body_avg, n, 2)
    assert s == pytest.approx({1: exp1, 3: exp3}, rel=1e-9)


def test_exact_bm25_phrase_and_prefix():
    i = small()
    s = scores(i, '"apple pie"')
    assert s == pytest.approx({3: bm25(1, 4, 8 / 3, 3, 1)}, rel=1e-9)
    p = scores(i, "che*")
    # one pseudo-term: tf = sum of tfs, df = docs with any expansion (per field)
    exp2 = 1.0 * bm25(1, 1, 8 / 3, 3, 1)
    exp3 = 2.0 * bm25(1, 2, 5 / 3, 3, 1)
    assert p == pytest.approx({2: exp2, 3: exp3}, rel=1e-9)


def test_custom_boosts():
    i = Index(boosts={"body": 3.0})
    i.add("apple", body="apple banana apple")
    i.add("banana split", body="cherry")
    i.add("cherry pie", body="apple pie recipe here")
    s = scores(i, "apple")
    exp1 = 2.0 * bm25(1, 1, 5 / 3, 3, 1) + 3.0 * bm25(2, 3, 8 / 3, 3, 2)
    assert s[1] == pytest.approx(exp1, rel=1e-9)
    with pytest.raises(ValueError):
        Index(boosts={"tags": 1.0})
    with pytest.raises(ValueError):
        Index(boosts={"title": 0})


def test_deleted_documents_leave_statistics():
    i = small()
    extra = i.add("apple apple", body="apple apple apple apple")
    i.delete(extra)
    assert scores(i, "apple") == pytest.approx(scores(small(), "apple"), rel=1e-12)


def test_api_scores_not_rounded_cli_rounded(tmp_path):
    i = small()
    s = scores(i, "apple")[3]
    assert s != round(s, 4)
    cli(tmp_path, "add", "apple", "--body", "apple banana apple")
    cli(tmp_path, "add", "banana split", "--body", "cherry")
    cli(tmp_path, "add", "cherry pie", "--body", "apple pie recipe here")
    lines = cli(tmp_path, "search", "apple").stdout.splitlines()
    assert lines[2] == f"3\t{s:.4f}\tcherry pie"
    data = json.loads(cli(tmp_path, "search", "apple", "--json").stdout)
    assert data["total"] == 2 and data["hits"][1]["score"] == pytest.approx(s, rel=1e-12)
    assert data["hits"][1]["score"] != round(data["hits"][1]["score"], 4)


def test_ties_broken_by_id():
    i = Index()
    for _ in range(4):
        i.add("same title", body="same body")
    assert i.search("same").ids() == [1, 2, 3, 4]
    assert i.search("-nothing").ids() == [1, 2, 3, 4]


def test_sort_by_date():
    i = Index()
    i.add("a x", date="2024-01-01")
    i.add("b x")
    i.add("c x", date="2024-06-01")
    i.add("d x", date="2024-01-01")
    assert i.search("x", sort="date").ids() == [3, 1, 4, 2]
    with pytest.raises(ValueError):
        i.search("x", sort="title")


def test_pagination_rules():
    i = Index()
    for n in range(5):
        i.add(f"doc {n}", body="word")
    assert i.search("word", per_page=2, page=3).ids() == [5]
    beyond = i.search("word", per_page=2, page=9)
    assert beyond.hits == [] and beyond.total == 5 and beyond.pages == 3
    for bad in ({"page": 0}, {"per_page": 0}, {"per_page": 101}):
        with pytest.raises(ValueError):
            i.search("word", **bad)


def test_title_match_ranks_above_body_match():
    i = Index()
    i.add("Notes", body="python tips and more words")
    i.add("Python", body="notes and more words here")
    assert i.search("python").ids() == [2, 1]
