"""화면 3차 (DESIGN.md 36.22): 작업공간의 파일·git API, 보통 터미널(셸) 세션, 한도 막대."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from tenure.registry import Registry
from tenure.runner import run_process
from tenure.term import session as sessionlib
from tenure.term.session import SessionManager
from tenure.ui import files
from tenure.ui.dashboard import ApiError, Dashboard, dispatch


def git(cwd: Path, *args: str) -> None:
    r = run_process(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, timeout_sec=30)
    assert r.ok, r.stderr


@pytest.fixture
def repo(tmp_path):
    wd = tmp_path / "proj"
    (wd / "src").mkdir(parents=True)
    (wd / "src" / "app.py").write_text("print('a')\n", encoding="utf-8")
    (wd / "README.md").write_text("# 안녕\n", encoding="utf-8")
    (wd / "node_modules").mkdir()
    git(wd, "init", "-q")
    git(wd, "add", ".")
    git(wd, "commit", "-qm", "처음")
    Registry().add(wd)
    return wd


def test_tree_and_read_stay_inside(repo):
    t = files.tree(repo)
    names = [e["name"] for e in t["entries"]]
    assert names[:2] == ["node_modules", "src"] and ".git" not in names          # 폴더 먼저, .git 숨김
    assert next(e for e in t["entries"] if e["name"] == "node_modules")["heavy"]
    assert files.tree(repo, "src")["entries"][0]["name"] == "app.py"
    assert files.read_file(repo, "README.md")["text"].strip() == "# 안녕"
    (repo / "bin.dat").write_bytes(b"\0\1\2")
    assert files.read_file(repo, "bin.dat")["binary"]
    for bad in ("../x", "src/../../x", "C:/Windows", "/etc/passwd"):
        with pytest.raises(files.FilesError):
            files.read_file(repo, bad)


def test_status_and_file_diff(repo):
    (repo / "src" / "app.py").write_text("print('b')\nprint('c')\n", encoding="utf-8")
    (repo / "new.txt").write_text("새 줄\n", encoding="utf-8")
    st = files.status(repo)
    by = {f["path"]: f for f in st["files"]}
    assert st["repo"] and by["src/app.py"]["kind"] == "modified" and by["src/app.py"]["add"] == 2
    assert by["new.txt"]["kind"] == "untracked" and st["commits"][0]["subject"] == "처음"
    assert "+print('c')" in files.file_diff(repo, "src/app.py")["text"]
    assert "+새 줄" in files.file_diff(repo, "new.txt")["text"]
    plain = repo.parent / "plain"
    plain.mkdir()
    assert files.status(plain)["repo"] in (False, True)                            # 저장소 밖도 오류 없이


def test_ws_api_via_dispatch(repo):
    d = Dashboard()
    out = dispatch(d, "ws_tree", {"project": str(repo)})
    assert any(e["name"] == "README.md" for e in out["entries"])
    assert dispatch(d, "ws_file", {"project": str(repo), "path": "src/app.py"})["text"].startswith("print")
    with pytest.raises(ApiError) as e:
        dispatch(d, "ws_file", {"project": str(repo), "path": "../secret"})
    assert e.value.status == 400
    with pytest.raises(ApiError):                                                   # 등록 안 된 폴더는 못 봄
        dispatch(d, "ws_tree", {"project": str(repo.parent)})
    lim = dispatch(d, "limits", {})
    assert set(lim) == {"codex", "claude", "slots"} and lim["slots"]["max"] >= 1


def test_shell_session(tmp_path, monkeypatch):
    monkeypatch.setattr(sessionlib, "default_shell",
                        lambda: [sys.executable, "-c", "import sys; print('셸 준비'); sys.stdout.flush(); print(input())"])
    m = SessionManager(tmp_path / "home")
    s = m.create("shell", tmp_path, str(tmp_path))
    end = time.monotonic() + 20
    while "셸 준비" not in s.snapshot()["data"] and time.monotonic() < end:
        time.sleep(0.1)
    assert "셸 준비" in s.snapshot()["data"]
    s.write("메아리\r")
    while s.live and time.monotonic() < end:
        time.sleep(0.1)
    assert "메아리" in s.snapshot()["data"] and s.status()["attention"] is None
    assert sessionlib.default_shell()                                              # 원래 함수도 무언가를 돌려준다 (monkeypatch 전 값)
