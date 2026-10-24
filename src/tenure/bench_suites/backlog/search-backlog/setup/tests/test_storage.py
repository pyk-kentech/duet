import json

import pytest

from findex import Index, StorageError


def sample():
    i = Index(stopwords=["foo"], stem=False, boosts={"title": 3.0})
    i.add("Hello world", body="foo bar baz", tags=["x"], date="2024-05-01")
    i.add("Second doc", body="the world is big")
    return i


def test_roundtrip(tmp_path):
    i = sample()
    i.save(tmp_path / "i.json")
    j = Index.load(tmp_path / "i.json")
    assert [d.to_dict() for d in j.documents()] == [d.to_dict() for d in i.documents()]
    for q in ["world", "foo", "the", "title:hello", "tag:x"]:
        assert [(h.doc_id, h.score) for h in j.search(q).hits] == [(h.doc_id, h.score) for h in i.search(q).hits]


def test_settings_kept(tmp_path):
    sample().save(tmp_path / "i.json")
    j = Index.load(tmp_path / "i.json")
    assert j.analyzer.stem is False and j.boosts["title"] == 3.0
    assert j.search("foo").total == 0


def test_format_marker(tmp_path):
    sample().save(tmp_path / "i.json")
    data = json.loads((tmp_path / "i.json").read_text(encoding="utf-8"))
    assert data["format"] == "findex" and len(data["documents"]) == 2


def test_broken_file(tmp_path):
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(StorageError):
        Index.load(tmp_path / "bad.json")


def test_missing_file(tmp_path):
    with pytest.raises(StorageError):
        Index.load(tmp_path / "nope.json")
