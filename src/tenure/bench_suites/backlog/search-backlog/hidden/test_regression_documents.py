"""기존 동작 (README "문서"·"id"·API 절)."""

import pytest

from findex import DocumentNotFound, Index


def test_ids_never_reused_after_deleting_last():
    i = Index()
    i.add("a")
    i.add("b")
    c = i.add("c")
    i.delete(c)
    assert i.next_id == 4
    assert i.add("d") == 4


def test_ids_never_reused_after_save_and_load(tmp_path):
    i = Index()
    i.add("a")
    i.add("b")
    i.add("c")
    i.delete(3)
    i.delete(2)
    i.save(tmp_path / "i.json")
    j = Index.load(tmp_path / "i.json")
    assert j.ids() == [1] and j.next_id == 4
    assert j.add("d") == 4
    with pytest.raises(DocumentNotFound):
        j.get(3)


def test_documents_returned_verbatim():
    i = Index()
    d = i.add("  Spaced Title  ", body="Body\n  with  spaces")
    doc = i.get(d)
    assert doc.title == "  Spaced Title  " and doc.body == "Body\n  with  spaces"
    assert doc.date is None and doc.tags == ()
    assert i.documents() == [doc]


def test_tag_cleaning():
    i = Index()
    d = i.add("t", tags=["  Python ", "", "python", "Web", "PYTHON", "   "])
    assert i.get(d).tags == ("Python", "Web")


def test_date_validation():
    i = Index()
    for bad in ("2024-03", "2024-02-30", "2024/01/01", "24-01-01"):
        with pytest.raises(ValueError):
            i.add("x", date=bad)
    assert len(i) == 0 and i.next_id == 1
    assert i.get(i.add("x", date="2024-02-29")).date == "2024-02-29"


def test_missing_and_deleted_ids():
    i = Index()
    d = i.add("x")
    i.delete(d)
    assert d not in i and len(i) == 0
    for call in (lambda: i.get(d), lambda: i.delete(d), lambda: i.update(d, title="y"), lambda: i.get(42)):
        with pytest.raises(DocumentNotFound):
            call()


def test_add_many_is_all_or_nothing():
    i = Index()
    i.add("first")
    with pytest.raises(ValueError) as e:
        i.add_many([{"title": "ok"}, {"title": "fine", "date": "2024-01-01"}, {"title": ""}])
    assert "3" in str(e.value)
    assert len(i) == 1 and i.next_id == 2
    assert i.add_many([{"title": "a", "tags": ["x"]}, {"title": "b", "body": "bee"}]) == [2, 3]


def test_update_none_keeps_fields():
    i = Index()
    d = i.add("Title", body="body words", tags=["t"], date="2024-01-01")
    doc = i.update(d, title="New title")
    assert (doc.id, doc.title, doc.body, doc.tags, doc.date) == (d, "New title", "body words", ("t",), "2024-01-01")
    i.update(d, tags=[])
    assert i.get(d).tags == ()


def test_check_and_reindex_on_healthy_index():
    i = Index()
    i.add("Send e-mail to Zoë", body="state-of-the-art café menu; x--y and 3.14", tags=["Café", "e-mail"])
    i.add("Crème brûlée", body="naïve but well-known recipe", tags=["cafe"], date="2024-02-03")
    i.add("Plain words", body="nothing special here")
    i.delete(3)
    assert i.check() == []
    before = {q: {h.doc_id: h.score for h in i.search(q).hits} for q in ["menu", "recipe", "zoe", "send"]}
    assert i.reindex() == 2
    assert i.check() == [] and len(i) == 2 and i.next_id == 4
    after = {q: {h.doc_id: h.score for h in i.search(q).hits} for q in ["menu", "recipe", "zoe", "send"]}
    for q in before:
        assert after[q] == pytest.approx(before[q], rel=1e-12), q


def test_similar_and_stats():
    i = Index()
    a = i.add("python tips", body="python list tips")
    b = i.add("python tricks", body="python list tricks")
    i.add("gardening", body="roses and tulips")
    assert [h.doc_id for h in i.similar(a)] == [b]
    # terms: python, tip, list, trick, garden, rose, tulip
    assert i.stats() == {"documents": 3, "terms": 7, "next_id": 4}
