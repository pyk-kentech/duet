"""FX-105: 저장 형식 버전 3 (쓰기), 버전 1·2·3 읽기(언제나 다시 색인), 그 밖의 버전 거부."""

import copy
import json
import os
import subprocess
import sys

import pytest

from findex import Index, StorageError

V2 = {
    "format": "findex",
    "version": 2,
    "settings": {"stopwords": None, "stem": True, "boosts": {"title": 2.0, "body": 1.0}},
    "documents": [
        {"id": 1, "title": "Café menu", "body": "send an e-mail", "tags": ["Café"], "date": "2024-01-02"},
        {"id": 3, "title": "Other", "body": "plain text", "tags": [], "date": None},
    ],
    "index": {
        "next_id": 5,
        "fields": {
            "title": {"café": {"1": [0]}, "menu": {"1": [1]}, "other": {"3": [0]}},
            "body": {"send": {"1": [0]}, "e": {"1": [1]}, "mail": {"1": [2]}, "plain": {"3": [0]},
                     "text": {"3": [1]}},
            "tags": {"café": {"1": [0]}},
        },
        "lengths": {"title": {"1": 2, "3": 1}, "body": {"1": 3, "3": 2}},
    },
}

V1 = {
    "version": 1,
    "next_id": 7,
    "docs": {
        "2": {"title": "Crème brûlée", "text": "a naïve dessert", "tags": "Food,dessert", "date": "2023-05-06"},
        "5": {"title": "Second", "text": "x-ray notes"},
    },
}


def ids(idx, q):
    return sorted(idx.search(q, per_page=100).ids())


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def cli(tmp_path, *args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "findex", "--index", str(tmp_path / "i.json"), *args],
                          capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(tmp_path))


def test_save_writes_version_3(tmp_path):
    i = Index(stopwords=["foo"], stem=False, boosts={"title": 3.0})
    i.add("Hello", body="world", tags=["x"], date="2024-01-02")
    i.add("Second")
    i.delete(2)
    i.save(tmp_path / "i.json")
    data = read(tmp_path / "i.json")
    assert data["format"] == "findex" and data["version"] == 3
    assert "index" not in data
    assert data["next_id"] == 3
    assert data["settings"] == {"stopwords": ["foo"], "stem": False, "boosts": {"title": 3.0, "body": 1.0},
                                "synonyms": []}
    assert data["documents"] == [{"id": 1, "title": "Hello", "body": "world", "tags": ["x"], "date": "2024-01-02"}]


def test_synonyms_are_saved_and_loaded(tmp_path):
    i = Index()
    a = i.add("automobile club")
    i.add_synonyms("car", "Automobile")
    i.add_synonyms("bike", "bicycle")
    i.save(tmp_path / "i.json")
    assert read(tmp_path / "i.json")["settings"]["synonyms"] == [["car", "Automobile"], ["bike", "bicycle"]]
    j = Index.load(tmp_path / "i.json")
    assert j.synonyms() == [["car", "Automobile"], ["bike", "bicycle"]]
    assert ids(j, "car") == [a]


def test_saved_documents_verbatim_without_index(tmp_path):
    i = Index()
    i.add("Crème", body="naïve x-ray", tags=["Café"])
    i.add("gone")
    i.delete(2)
    i.save(tmp_path / "i.json")
    data = read(tmp_path / "i.json")
    assert "index" not in data and data["next_id"] == 3
    assert data["documents"] == [{"id": 1, "title": "Crème", "body": "naïve x-ray", "tags": ["Café"],
                                  "date": None}]


def test_roundtrip_scores_identical(tmp_path):
    i = Index()
    i.add("Crème brûlée", body="send an e-mail about the naïve café")
    i.add("Email basics", body="mail and e mail")
    i.add("Other", body="plain words", tags=["Café"])
    i.save(tmp_path / "i.json")
    j = Index.load(tmp_path / "i.json")
    for q in ["creme", "email", "mail", '"send email"', "cafe", "tag:cafe", "e-mail", "ema*"]:
        a = {h.doc_id: h.score for h in i.search(q).hits}
        b = {h.doc_id: h.score for h in j.search(q).hits}
        assert a and a == pytest.approx(b), q


def test_load_v2_reindexes_with_current_rules(tmp_path):
    i = Index.load(write(tmp_path / "old.json", V2))
    assert ids(i, "cafe") == [1]
    assert ids(i, "email") == [1]
    assert ids(i, "tag:cafe") == [1]
    assert ids(i, "plain") == [3]
    assert i.get(1).title == "Café menu"


def test_load_v2_keeps_next_id_and_settings(tmp_path):
    data = copy.deepcopy(V2)
    data["settings"] = {"stopwords": ["plain"], "stem": False, "boosts": {"title": 4.0, "body": 1.0}}
    data["documents"][1]["body"] = "plain texts"
    i = Index.load(write(tmp_path / "old.json", data))
    assert i.next_id == 5
    assert ids(i, "plain") == []            # custom stopword kept
    assert ids(i, "text") == []             # stem=False kept
    assert ids(i, "texts") == [3]
    assert i.add("new") == 5


def test_load_v2_then_save_writes_v3(tmp_path):
    i = Index.load(write(tmp_path / "old.json", V2))
    i.save(tmp_path / "new.json")
    data = read(tmp_path / "new.json")
    assert data["version"] == 3 and data["next_id"] == 5 and "index" not in data
    assert data["documents"] == V2["documents"]
    assert data["settings"]["synonyms"] == []


def test_load_v1_with_current_rules(tmp_path):
    i = Index.load(write(tmp_path / "v1.json", V1))
    assert i.ids() == [2, 5] and i.next_id == 7
    assert i.get(2).tags == ("Food", "dessert") and i.get(2).body == "a naïve dessert"
    assert ids(i, "creme") == [2]
    assert ids(i, "xray") == [5]
    assert i.add("new") == 7


@pytest.mark.parametrize("version", [4, 99])
def test_future_versions_rejected(tmp_path, version):
    data = {"format": "findex", "version": version, "settings": {}, "next_id": 2,
            "documents": [{"id": 1, "title": "t", "body": "", "tags": [], "date": None}]}
    with pytest.raises(StorageError) as e:
        Index.load(write(tmp_path / "f.json", data))
    assert str(version) in str(e.value)


def test_other_bad_versions_and_formats_rejected(tmp_path):
    base = {"format": "findex", "settings": {}, "next_id": 1, "documents": []}
    for version in (0, "3", 2.5, None):
        data = dict(base, version=version)
        if version is None:
            del data["version"]
        with pytest.raises(StorageError):
            Index.load(write(tmp_path / "f.json", data))
    for version in (2, 3):
        with pytest.raises(StorageError):
            Index.load(write(tmp_path / "f.json", dict(base, version=version, format="other")))


def test_cli_works_on_v2_and_rewrites_v3(tmp_path):
    write(tmp_path / "i.json", V2)
    r = cli(tmp_path, "search", "cafe")
    assert r.stdout.splitlines()[0] == "검색 결과 1건"
    assert read(tmp_path / "i.json")["version"] == 2          # read-only command does not save
    assert cli(tmp_path, "add", "New").stdout.strip() == "5"
    data = read(tmp_path / "i.json")
    assert data["version"] == 3 and data["next_id"] == 6 and len(data["documents"]) == 3


def test_cli_refuses_unknown_version_and_keeps_file(tmp_path):
    raw = json.dumps({"format": "findex", "version": 4, "settings": {}, "next_id": 1, "documents": []})
    (tmp_path / "i.json").write_text(raw, encoding="utf-8")
    r = cli(tmp_path, "add", "x")
    assert r.returncode == 1 and r.stderr.startswith("오류:")
    assert (tmp_path / "i.json").read_text(encoding="utf-8") == raw
