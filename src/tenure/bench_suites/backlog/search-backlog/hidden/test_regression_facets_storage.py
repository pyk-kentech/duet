"""기존 동작 (README "facets"·"저장 형식" 절)."""

import json
import os

import pytest

from findex import Index, StorageError


def test_facet_label_from_earliest_live_document():
    i = Index()
    i.add("a", tags=["Python"])
    i.add("b", tags=["python", "Web"])
    i.add("c", tags=["PYTHON"])
    assert i.facets() == [("Python", 3), ("Web", 1)]
    i.delete(1)
    assert i.facets() == [("python", 2), ("Web", 1)]
    assert i.facets("c") == [("PYTHON", 1)]


def test_facet_order_and_limit():
    i = Index()
    i.add("a", tags=["beta", "Alpha"])
    i.add("b", tags=["gamma", "beta"])
    i.add("c", tags=["alpha", "delta"])
    assert i.facets() == [("Alpha", 2), ("beta", 2), ("delta", 1), ("gamma", 1)]
    assert i.facets(limit=3) == [("Alpha", 2), ("beta", 2), ("delta", 1)]
    with pytest.raises(ValueError):
        i.facets(limit=0)


def test_facets_for_query_count_all_matches_not_one_page():
    i = Index()
    for n in range(15):
        i.add(f"item {n}", tags=["even" if n % 2 == 0 else "odd"])
    assert i.facets("item") == [("even", 8), ("odd", 7)]
    assert i.facets("nothing") == []


def test_load_version_1_file(tmp_path):
    data = {"version": 1, "next_id": 9, "docs": {
        "3": {"title": "Old doc", "text": "legacy body words", "tags": "a, b ,a", "date": "2020-02-02"},
        "4": {"title": "Another"}}}
    (tmp_path / "v1.json").write_text(json.dumps(data), encoding="utf-8")
    i = Index.load(tmp_path / "v1.json")
    assert i.ids() == [3, 4] and i.next_id == 9
    doc = i.get(3)
    assert (doc.body, doc.tags, doc.date) == ("legacy body words", ("a", "b"), "2020-02-02")
    assert i.search("legacy").ids() == [3]
    assert i.search("old").ids() == [3]


def test_settings_survive_roundtrip(tmp_path):
    i = Index(stopwords=["apple"], stem=False, boosts={"title": 5.0})
    i.add("apple pies", body="the pies")
    i.save(tmp_path / "i.json")
    j = Index.load(tmp_path / "i.json")
    assert j.search("apple").total == 0
    assert j.search("pie").total == 0 and j.search("pies").total == 1
    assert j.search("the").total == 1
    a = {h.doc_id: h.score for h in i.search("pies").hits}
    b = {h.doc_id: h.score for h in j.search("pies").hits}
    assert a == pytest.approx(b)


def test_broken_and_missing_files(tmp_path):
    (tmp_path / "bad.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(StorageError):
        Index.load(tmp_path / "bad.json")
    with pytest.raises(StorageError):
        Index.load(tmp_path / "missing.json")
    (tmp_path / "list.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(StorageError):
        Index.load(tmp_path / "list.json")


def test_save_leaves_no_temp_files(tmp_path):
    i = Index()
    i.add("x")
    i.save(tmp_path / "i.json")
    i.add("y")
    i.save(tmp_path / "i.json")
    assert os.listdir(tmp_path) == ["i.json"]
    assert Index.load(tmp_path / "i.json").ids() == [1, 2]
