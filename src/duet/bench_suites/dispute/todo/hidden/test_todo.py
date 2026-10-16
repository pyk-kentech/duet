import json
import subprocess
import sys

import pytest

import todo
from todo import StoreError, TodoStore


def test_add_ids_and_items(tmp_path):
    s = TodoStore(tmp_path / "t.json")
    assert s.add("  우유 사기 ") == 1
    assert s.add("빨래") == 2
    assert s.items() == [{"id": 1, "title": "우유 사기", "done": False},
                         {"id": 2, "title": "빨래", "done": False}]


def test_missing_file_starts_empty_and_is_created_on_save(tmp_path):
    p = tmp_path / "sub" / "t.json"
    p.parent.mkdir()
    s = TodoStore(str(p))
    assert s.items() == [] and not p.exists()
    s.add("a")
    assert p.exists()


@pytest.mark.parametrize("bad", ["", "   ", "\t\n"])
def test_empty_title_rejected(tmp_path, bad):
    s = TodoStore(tmp_path / "t.json")
    with pytest.raises(ValueError):
        s.add(bad)
    assert s.items() == []


def test_ids_not_reused_after_remove_even_after_reopen(tmp_path):
    p = tmp_path / "t.json"
    s = TodoStore(p)
    s.add("a")
    s.add("b")
    s.remove(2)
    s.remove(1)
    assert TodoStore(p).add("c") == 3


def test_done_and_filter(tmp_path):
    s = TodoStore(tmp_path / "t.json")
    for t in ("a", "b", "c"):
        s.add(t)
    s.done(2)
    assert [x["id"] for x in s.items(include_done=False)] == [1, 3]
    assert [x["done"] for x in s.items()] == [False, True, False]


def test_unknown_id_keyerror(tmp_path):
    s = TodoStore(tmp_path / "t.json")
    s.add("a")
    with pytest.raises(KeyError):
        s.done(5)
    with pytest.raises(KeyError):
        s.remove(5)


def test_persists_immediately_and_format(tmp_path):
    p = tmp_path / "t.json"
    s = TodoStore(p)
    s.add("한글 제목")
    s.done(1)
    raw = p.read_text(encoding="utf-8")
    assert "한글 제목" in raw
    data = json.loads(raw)
    assert data == {"next_id": 2, "items": [{"id": 1, "title": "한글 제목", "done": True}]}
    assert TodoStore(p).items() == [{"id": 1, "title": "한글 제목", "done": True}]


@pytest.mark.parametrize("content", ["{not json", "[]", '{"items": []}', '{"next_id": 1, "items": {}}'])
def test_corrupt_file_store_error(tmp_path, content):
    p = tmp_path / "t.json"
    p.write_text(content, encoding="utf-8")
    with pytest.raises(StoreError):
        TodoStore(p)
    assert issubclass(todo.StoreError, Exception)


def cli(tmp_path, *args):
    return subprocess.run([sys.executable, "-m", "todo", *args], cwd=tmp_path, capture_output=True,
                          text=True, encoding="utf-8", timeout=30)


def test_cli_flow_default_file(tmp_path):
    r = cli(tmp_path, "add", "장", "보기")
    assert r.returncode == 0 and r.stdout.strip() == "added 1"
    assert cli(tmp_path, "add", "청소").stdout.strip() == "added 2"
    r = cli(tmp_path, "done", "1")
    assert r.returncode == 0 and r.stdout == ""
    assert cli(tmp_path, "list").stdout.splitlines() == ["2. [ ] 청소"]
    assert cli(tmp_path, "list", "--all").stdout.splitlines() == ["1. [x] 장 보기", "2. [ ] 청소"]
    assert (tmp_path / "todo.json").exists()
    assert cli(tmp_path, "rm", "2").returncode == 0
    assert cli(tmp_path, "list", "--all").stdout.splitlines() == ["1. [x] 장 보기"]


def test_cli_file_option(tmp_path):
    r = cli(tmp_path, "--file", "other.json", "add", "x")
    assert r.returncode == 0 and (tmp_path / "other.json").exists() and not (tmp_path / "todo.json").exists()


def test_cli_exit_codes(tmp_path):
    r = cli(tmp_path, "done", "9")
    assert r.returncode == 1 and r.stderr.strip()
    assert cli(tmp_path, "rm", "9").returncode == 1
    assert cli(tmp_path, "add", " ").returncode == 2
    (tmp_path / "todo.json").write_text("{broken", encoding="utf-8")
    assert cli(tmp_path, "list").returncode == 3
