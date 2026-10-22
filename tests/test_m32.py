"""M32: 작업마다 worktree·병합 준비 점검·병합·버리기·줄 메모 (DESIGN.md 36.14)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from tenure import merge, notes, worktree
from tenure.orchestrator import Orchestrator, OrchestratorError, RunOptions
from tenure.state import RunState, runs_root
from tenure.ui.dashboard import ApiError, Dashboard, dispatch
from tenure.workspace import Workspace


def repo(path: Path, files: dict[str, str] | None = None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    ws = Workspace(path)
    ws.git("init", "-q", "-b", "main")
    ws.git("config", "core.autocrlf", "false")
    for name, text in (files or {"README.md": "# 프로젝트\n", "DESIGN.md": "# 설계\n"}).items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text, encoding="utf-8")
    ws.git("add", "-A")
    ws.git("commit", "-q", "-m", "init")
    return path


def commit(path: Path, name: str, text: str, msg: str = "change") -> None:
    (path / name).write_text(text, encoding="utf-8")
    ws = Workspace(path)
    ws.git("add", "-A")
    ws.git("commit", "-q", "-m", msg)


def run(wd: Path, task: str = "할일 CLI", **kw):
    overrides = {"workflow": "quick", "worktree": "auto", "test_command": "none", "report": False,
                 **kw.pop("overrides", {})}
    return Orchestrator(printer=lambda line: None).run(
        RunOptions(task=task, workdir=wd, mock=True, overrides=overrides, **kw))


# ------------------------------------------------------------------ worktree
def test_should_use(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert not worktree.should_use(plain, "auto")
    empty = tmp_path / "empty"
    empty.mkdir()
    Workspace(empty).git("init", "-q")
    assert not worktree.should_use(empty, "auto")           # 커밋 없음
    r = repo(tmp_path / "r", {"a.txt": "a\n", "sub/b.txt": "b\n"})
    assert worktree.should_use(r, "auto")
    assert not worktree.should_use(r, "off")
    assert not worktree.should_use(r / "sub", "auto")        # 하위 폴더는 그대로
    assert not worktree.should_use(r / ".tenure" / "worktrees" / "x", "auto")


def test_run_in_worktree_leaves_project_untouched(tmp_path):
    wd = repo(tmp_path / "p")
    out = run(wd)
    rid = out.state.run_id
    tree = worktree.find(wd, rid)
    assert tree is not None and tree.status == worktree.OPEN and tree.branch == f"tenure/{rid}"
    assert tree.base_branch == "main" and Path(tree.path) == wd / ".tenure" / "worktrees" / rid
    assert out.run_dir == Path(tree.path) / ".tenure" / "runs" / rid
    assert (Path(tree.path) / "main.py").is_file() and not (wd / "main.py").exists()
    assert out.state.worktree["project"] == str(wd) and out.state.worktree["base_branch"] == "main"
    assert Workspace(wd).dirty_files() == []                  # .tenure 는 info/exclude 로 무시
    common = wd / ".git" / "info" / "exclude"
    assert ".tenure/" in common.read_text(encoding="utf-8").splitlines()
    assert [d.name for d in worktree.all_run_dirs(wd)] == [rid]


def test_two_runs_get_separate_worktrees_and_ids(tmp_path):
    wd = repo(tmp_path / "p")
    a = run(wd, run_id="20261021-100000")
    b = run(wd, run_id="20261021-100001")
    assert {t.run_id for t in worktree.load_index(wd)} == {"20261021-100000", "20261021-100001"}
    assert a.run_dir != b.run_dir
    with pytest.raises(OrchestratorError, match="이미 쓰였습니다"):
        run(wd, run_id="20261021-100000")


def test_off_and_design_only_stay_in_project(tmp_path):
    wd = repo(tmp_path / "p")
    out = run(wd, overrides={"worktree": "off"})
    assert out.run_dir.parent.parent.parent == wd and worktree.load_index(wd) == []
    wd2 = repo(tmp_path / "q")
    out2 = Orchestrator(printer=lambda line: None).run(RunOptions(
        task="설계만", workdir=wd2, mock=True, design_only=True, overrides={"worktree": "auto", "workflow": "classic"}))
    assert out2.run_dir.parent.parent.parent == wd2 and worktree.load_index(wd2) == []


def test_ignored_includes_are_copied(tmp_path):
    wd = repo(tmp_path / "p", {".gitignore": ".env\nsecret/\n*.local\n", "README.md": "x\n"})
    (wd / ".env").write_text("KEY=1\n", encoding="utf-8")
    (wd / "app.local").write_text("local\n", encoding="utf-8")
    (wd / ".tenureinclude").write_text("# 주석\n*.local\n", encoding="utf-8")
    commit(wd, ".tenureinclude", "# 주석\n*.local\n", "include")
    out = run(wd)
    tree = Path(out.state.worktree and worktree.find(wd, out.state.run_id).path)
    assert (tree / ".env").read_text(encoding="utf-8") == "KEY=1\n"
    assert (tree / "app.local").is_file()
    assert sorted(worktree.find(wd, out.state.run_id).note["included"]) == [".env", "app.local"]


# ------------------------------------------------------------------ merge
def test_readiness_and_squash_merge(tmp_path):
    wd = repo(tmp_path / "p")
    out = run(wd, task="할일 CLI\n자세한 설명")
    rid = out.state.run_id
    r = merge.readiness(wd, rid)
    levels = {c.key: c.level for c in r.checks}
    assert r.can_merge and levels["run"] == "ok" and levels["review"] == "ok" and levels["tests"] == "warn"
    assert r.ahead >= 1 and "main.py" in r.files and r.conflicts == []
    res = merge.merge(wd, rid)
    assert res["into"] == "main" and (wd / "main.py").is_file()
    assert Workspace(wd).git("log", "-1", "--format=%s").strip() == "할일 CLI"
    tree = worktree.find(wd, rid)
    assert tree.status == worktree.MERGED and tree.merged_commit == res["commit"]
    assert not Path(tree.path).exists()
    assert (runs_root(wd) / rid / "run.json").is_file()           # 기록은 프로젝트로 옮김
    assert Workspace(wd).git("rev-parse", "--verify", "--quiet", f"refs/heads/tenure/{rid}").strip()  # 브랜치는 남김
    assert not merge.readiness(wd, rid).can_merge
    with pytest.raises(merge.MergeError):
        merge.merge(wd, rid)


def test_conflict_blocks_then_resolve(tmp_path):
    wd = repo(tmp_path / "p")
    out = run(wd)
    rid = out.state.run_id
    commit(wd, "main.py", "print('main')\n")
    r = merge.readiness(wd, rid)
    levels = {c.key: c.level for c in r.checks}
    assert not r.can_merge and r.conflicts == ["main.py"] and levels["behind"] == "warn"
    rec = Orchestrator(printer=lambda line: None).followup(wd, rid, "resolve")
    assert rec["kind"] == "resolve" and rec["conflicts"] == ["main.py"]
    st = RunState.load(worktree.find(wd, rid).path and out.run_dir)
    assert st.followups[-1]["n"] == 1 and st.status == out.state.status
    r2 = merge.readiness(wd, rid)
    assert r2.can_merge and r2.conflicts == [] and r2.behind == 0
    merge.merge(wd, rid, merge.MERGE)
    assert "print('main')" in (wd / "main.py").read_text(encoding="utf-8")


def test_main_tree_changes(tmp_path):
    wd = repo(tmp_path / "p")
    rid = run(wd).state.run_id
    (wd / "notes.txt").write_text("x\n", encoding="utf-8")       # 추적 안 함, 겹치지 않음 → 주의
    levels = {c.key: c.level for c in merge.readiness(wd, rid).checks}
    assert levels["main_dirty"] == "warn"
    (wd / "main.py").write_text("x\n", encoding="utf-8")         # 병합할 파일과 겹침 → 막음
    assert {c.key: c.level for c in merge.readiness(wd, rid).checks}["main_dirty"] == "block"
    (wd / "main.py").unlink()
    (wd / "README.md").write_text("바뀜\n", encoding="utf-8")     # 추적 파일 변경 → 막음
    assert {c.key: c.level for c in merge.readiness(wd, rid).checks}["main_dirty"] == "block"
    Workspace(wd).git("checkout", "-b", "other")
    Workspace(wd).git("checkout", "--", "README.md")
    assert {c.key: c.level for c in merge.readiness(wd, rid).checks}["checkout"] == "block"


def test_discard_saves_patch(tmp_path):
    wd = repo(tmp_path / "p")
    out = run(wd)
    rid = out.state.run_id
    tree = worktree.find(wd, rid)
    (Path(tree.path) / "loose.txt").write_text("남은 변경\n", encoding="utf-8")
    assert {c.key: c.level for c in merge.readiness(wd, rid).checks}["tree_dirty"] == "warn"
    res = merge.discard(wd, rid)
    patch = wd / res["patch"]
    text = patch.read_text(encoding="utf-8")
    assert "main.py" in text and "loose.txt" in text
    assert worktree.find(wd, rid).status == worktree.DISCARDED and not Path(tree.path).exists()
    assert (runs_root(wd) / rid / "run.json").is_file()
    with pytest.raises(merge.MergeError, match="버린"):
        merge.discard(wd, rid)


# ------------------------------------------------------------------ notes
def test_notes_stale_and_send(tmp_path):
    wd = repo(tmp_path / "p")
    out = run(wd)
    rid, rd = out.state.run_id, out.run_dir
    code = Path(worktree.find(wd, rid).path)
    n = notes.add(rd, code, file="main.py", line=1, side="new", text="상수로 바꿔라", base=out.state.base_commit)
    assert n["line_text"] == "print('hi')" and n["status"] == "open"
    old = notes.add(rd, code, file="README.md", line=1, side="old", text="제목", base=out.state.base_commit)
    assert old["line_text"] == "# 프로젝트"
    for bad in ({"file": "../x", "line": 1}, {"file": "main.py", "line": 0}):
        with pytest.raises(notes.NoteError):
            notes.add(rd, code, side="new", text="x", base=None, **bad)
    assert [x["stale"] for x in notes.with_stale(rd, code, out.state.base_commit)] == [False, False]
    (code / "main.py").write_text("print('bye')\n" + (code / "main.py").read_text(encoding="utf-8"), encoding="utf-8")
    assert notes.with_stale(rd, code, out.state.base_commit)[0]["stale"] is True
    Workspace(code).git("checkout", "--", "main.py")
    head = Workspace(code).head()
    rec = Orchestrator(printer=lambda line: None).followup(wd, rid, "notes")
    assert rec["kind"] == "notes" and len(rec["notes"]) == 2 and rec["commit"] != head
    assert {x["status"] for x in notes.load(rd)} == {"sent"} and notes.load(rd)[0]["sent_round"] == 1
    assert next(rd.glob("*followup1_notes*")).is_file()
    text = notes.format_for_prompt(notes.load(rd))
    assert "1. main.py:1" in text and "줄: print('hi')" in text and "README.md:1 (바뀌기 전 줄)" in text
    with pytest.raises(OrchestratorError, match="보낼 메모"):
        Orchestrator(printer=lambda line: None).followup(wd, rid, "notes")


# ------------------------------------------------------------------ dashboard
def test_dashboard_sees_worktree_runs(tmp_path):
    wd = repo(tmp_path / "p")
    out = run(wd)
    rid = out.state.run_id
    d = Dashboard()
    runs = d.runs(str(wd))["runs"]
    assert runs[0]["run_id"] == rid and runs[0]["worktree"]["branch"] == f"tenure/{rid}"
    detail = d.run(str(wd), rid)
    assert detail["worktree"]["status"] == "open" and detail["code_dir"] == worktree.find(wd, rid).path
    assert "main.py" in d.diff(str(wd), rid)["text"]
    check = dispatch(d, "merge_check", {"project": str(wd), "run": rid})
    assert check["can_merge"] is True
    note = dispatch(d, "note_add", {"project": str(wd), "run": rid, "file": "main.py", "line": 1, "text": "메모"})["note"]
    assert dispatch(d, "notes", {"project": str(wd), "run": rid})["notes"][0]["id"] == note["id"]
    assert d.run(str(wd), rid)["notes_open"] == 1
    dispatch(d, "note_delete", {"project": str(wd), "run": rid, "id": note["id"]})
    with pytest.raises(ApiError):
        dispatch(d, "note_delete", {"project": str(wd), "run": rid, "id": note["id"]})
    res = dispatch(d, "merge", {"project": str(wd), "run": rid})
    assert res["into"] == "main"
    # 병합 뒤에도 기록·변경 사항을 볼 수 있다(브랜치 기준)
    assert d.run(str(wd), rid)["worktree"]["status"] == "merged"
    assert "main.py" in d.diff(str(wd), rid)["text"]
    assert d.commits(str(wd), rid)["commits"]


def test_reserve_run_id_unique(tmp_path):
    wd = repo(tmp_path / "p")
    d = Dashboard()
    ids = {d._reserve_run_id(wd, git=True) for _ in range(3)}
    assert len(ids) == 3


def test_utf8_output_even_when_isatty(monkeypatch):
    """Windows 의 NUL 은 isatty() 가 참이다. 그래도 cp949 면 UTF-8 로 바꿔 — 같은 글자로 죽지 않게."""
    from tenure import cli

    class Fake(io.TextIOWrapper):
        def isatty(self):
            return True

    out = Fake(io.BytesIO(), encoding="cp949")
    monkeypatch.setattr(cli.sys, "stdout", out)
    monkeypatch.setattr(cli.sys, "stderr", out)
    cli._utf8_output()
    assert out.encoding.lower().replace("-", "") == "utf8"
    print("— ✅", file=out)
