"""FX-103: update 뒤의 색인은 처음부터 바뀐 내용으로 넣은 것과 같다. date="" 는 날짜를 지운다."""

import os
import subprocess
import sys

import pytest

from findex import DocumentNotFound, Index

DOCS = [
    ("Apple pie", "sweet apple dessert", ["food"]),
    ("Banana", "apple banana smoothie apple", ["fruit", "drink"]),
    ("Cherry", "cherry tart", ["food"]),
]


def build(docs):
    i = Index()
    for title, body, tags in docs:
        i.add(title, body=body, tags=tags)
    return i


def ids(idx, q):
    return sorted(idx.search(q, per_page=100).ids())


def scores(idx, q):
    return {h.doc_id: h.score for h in idx.search(q, per_page=100).hits}


def same_scores(a, b):
    assert set(a) == set(b)
    for d in a:
        assert a[d] == pytest.approx(b[d], rel=1e-9, abs=1e-12), d


def cli(tmp_path, *args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "findex", "--index", str(tmp_path / "i.json"), *args],
                          capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(tmp_path))


def test_removed_word_no_longer_matches():
    i = build(DOCS)
    i.update(2, body="banana bread")
    assert ids(i, "smoothie") == []
    assert ids(i, "bread") == [2]
    assert ids(i, "apple") == [1]


def test_scores_equal_fresh_index():
    i = build(DOCS)
    i.update(2, body="apple bread")
    fresh = build([DOCS[0], ("Banana", "apple bread", ["fruit", "drink"]), DOCS[2]])
    for q in ["apple", "bread", "banana", '"apple bread"', "app*", "-cherry", "apple OR cherry"]:
        same_scores(scores(i, q), scores(fresh, q))


def test_title_only_update_keeps_id_and_body_scores():
    i = build(DOCS)
    i.update(2, title="Big banana")
    fresh = build([DOCS[0], ("Big banana", DOCS[1][1], DOCS[1][2]), DOCS[2]])
    assert len(i) == 3 and i.ids() == [1, 2, 3] and i.next_id == 4
    assert ids(i, "big") == [2]
    same_scores(scores(i, "smoothie"), scores(fresh, "smoothie"))
    same_scores(scores(i, "banana"), scores(fresh, "banana"))
    assert i.add("D") == 4


def test_stale_positions_do_not_make_phrases():
    i = Index()
    d = i.add("t", body="alpha beta")
    i.update(d, body="beta gamma alpha")
    assert ids(i, '"alpha beta"') == []
    assert ids(i, '"beta gamma"') == [d]


def test_check_is_clean_after_updates():
    i = build(DOCS)
    i.update(1, body="totally new text", tags=["new"])
    i.update(2, title="Banana split")
    i.update(1, body="sweet apple dessert again")
    assert i.check() == []
    assert i.reindex() == 3 and i.check() == []


def test_tag_filter_after_update():
    i = build(DOCS)
    i.update(1, tags=["dessert"])
    assert ids(i, "tag:food") == [3]
    assert ids(i, "tag:dessert") == [1]


def test_facets_for_query_after_update():
    i = build(DOCS)
    i.update(3, tags=["fruit"])
    assert i.facets() == [("fruit", 2), ("drink", 1), ("food", 1)]
    assert i.facets("tag:food") == [("food", 1)]


def test_suggest_after_update():
    i = build(DOCS)
    i.update(2, body="kiwi")
    assert i.suggest("smoo") == []
    assert i.suggest("kiw") == [("kiwi", 1)]


def test_update_can_clear_date():
    i = Index()
    d = i.add("x", date="2024-01-02")
    e = i.add("z", date="2024-05-05")
    i.update(d, date="")
    assert i.get(d).date is None
    assert ids(i, "date:2024") == [e]
    i.update(d, title="y")
    assert i.get(d).date is None
    i.update(e, title="zz")
    assert i.get(e).date == "2024-05-05"


def test_update_errors_leave_document_untouched():
    i = build(DOCS)
    with pytest.raises(DocumentNotFound):
        i.update(9, title="x")
    i.delete(3)
    with pytest.raises(DocumentNotFound):
        i.update(3, title="x")
    with pytest.raises(ValueError):
        i.update(1, title="  ", body="replaced")
    assert i.get(1).title == "Apple pie" and i.get(1).body == "sweet apple dessert"
    assert ids(i, "apple") == [1, 2]
    assert ids(i, "replaced") == []


def test_cli_update_clears_date_and_reindexes(tmp_path):
    cli(tmp_path, "add", "Note", "--body", "old words", "--date", "2024-01-01")
    r = cli(tmp_path, "update", "1", "--date", "", "--body", "new words")
    assert r.returncode == 0, r.stderr
    assert "date: -" in cli(tmp_path, "get", "1").stdout.splitlines()
    assert cli(tmp_path, "search", "old").stdout.splitlines() == ["검색 결과 0건"]
    assert cli(tmp_path, "search", "new").stdout.splitlines()[0] == "검색 결과 1건"
