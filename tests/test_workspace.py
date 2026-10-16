import os
from pathlib import Path

import pytest

from duet.workspace import GITIGNORE_ARTIFACTS, GitError, Workspace, WorkdirRefused, check_workdir


def test_ensure_repo_and_gitignore(tmp_path: Path):
    wd = tmp_path / "proj"
    ws = Workspace(wd)
    assert not ws.is_repo()
    ws.ensure_repo()
    assert ws.is_repo() and not ws.has_commits()
    text = (wd / ".gitignore").read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == ".duet/"
    for pat in ("__pycache__/", "*.py[cod]", ".pytest_cache/", "node_modules/"):
        assert pat in lines
    # 두 번 불러도 중복 추가 없음
    ws.ensure_repo()
    assert (wd / ".gitignore").read_text(encoding="utf-8") == text


def test_gitignore_appended_to_existing(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("*.pyc", encoding="utf-8")
    Workspace(tmp_path).ensure_repo()
    # 이미 있는 파일에는 .duet/ 만 덧붙이고 부산물 규칙은 넣지 않는다
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == "*.pyc\n.duet/\n"


def test_existing_empty_gitignore_left_alone(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("", encoding="utf-8")
    Workspace(tmp_path).ensure_repo()
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == ".duet/\n"


def test_existing_gitignore_with_duet_untouched(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("dist/\n.duet/\n", encoding="utf-8")
    Workspace(tmp_path).ensure_repo()
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == "dist/\n.duet/\n"


def test_new_gitignore_keeps_artifacts_out_of_commits(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.ensure_repo()
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("print(1)\n", encoding="utf-8")
    # 에이전트가 직접 돌린 pytest 가 남기는 것들
    for rel in ("app/__pycache__/main.cpython-312.pyc", "app/__pycache__/main.cpython-310.pyc",
                ".pytest_cache/v/cache/nodeids", "pkg.egg-info/PKG-INFO", "node_modules/x/index.js",
                "stray.pyc"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    ws.commit_all("duet: impl round 1")
    tracked = ws.git("ls-files").split()
    assert sorted(tracked) == [".gitignore", "app/main.py"]
    assert not ws.dirty()
    assert len(GITIGNORE_ARTIFACTS) == len(set(GITIGNORE_ARTIFACTS))


def test_commit_diff_dirty_restore(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.ensure_repo()
    (tmp_path / "DESIGN.md").write_text("design", encoding="utf-8")
    (tmp_path / ".duet").mkdir()
    (tmp_path / ".duet" / "x").write_text("ignored", encoding="utf-8")
    base = ws.commit_all("duet: design")
    assert len(base) >= 7 and ws.commit_count() == 1 and not ws.dirty()

    (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "DESIGN.md").write_text("design changed", encoding="utf-8")
    assert ws.dirty() and sorted(ws.dirty_files()) == ["DESIGN.md", "main.py"]
    head = ws.commit_all("duet: impl round 1")
    assert ws.commit_count() == 2 and head != base

    d = ws.diff(base, "HEAD", exclude=["DESIGN.md"])
    assert "main.py" in d and "print('hi')" in d and "design changed" not in d
    assert "design changed" in ws.diff(base)

    # 리뷰어가 파일을 건드린 상황 → 되돌림(.duet 은 보존)
    (tmp_path / "main.py").write_text("hacked", encoding="utf-8")
    (tmp_path / "evil.txt").write_text("new", encoding="utf-8")
    (tmp_path / ".duet" / "y").write_text("keep", encoding="utf-8")
    assert ws.dirty()
    ws.restore_clean()
    assert not ws.dirty()
    assert (tmp_path / "main.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert not (tmp_path / "evil.txt").exists()
    assert (tmp_path / ".duet" / "y").exists()

    # 빈 커밋 허용
    assert ws.commit_all("empty") and ws.commit_count() == 3


def test_git_error(tmp_path: Path):
    ws = Workspace(tmp_path)
    with pytest.raises(GitError):
        ws.git("rev-parse", "HEAD")  # 저장소 아님


def test_missing_git_binary(tmp_path: Path):
    with pytest.raises(GitError, match="git"):
        Workspace(tmp_path, git_bin="no-such-git-xyz").git("status")


def test_check_workdir_refuses_home_and_root():
    with pytest.raises(WorkdirRefused):
        check_workdir(Path.home())
    with pytest.raises(WorkdirRefused):
        check_workdir(Path("/"))


def test_check_workdir_dirty_repo(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.ensure_repo()
    ws.commit_all("init")
    assert check_workdir(tmp_path) == tmp_path.resolve()
    (tmp_path / "wip.txt").write_text("x", encoding="utf-8")
    with pytest.raises(WorkdirRefused, match="wip.txt"):
        check_workdir(tmp_path)
    assert check_workdir(tmp_path, force=True) == tmp_path.resolve()


def test_check_workdir_nonexistent_and_plain_dir(tmp_path: Path):
    assert check_workdir(tmp_path / "new") == (tmp_path / "new").resolve()
    (tmp_path / "f.txt").write_text("x")
    assert check_workdir(tmp_path) == tmp_path.resolve()   # git 저장소 아니면 변경 검사 안 함
    with pytest.raises(WorkdirRefused):
        check_workdir(tmp_path / "f.txt")
