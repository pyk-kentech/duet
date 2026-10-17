"""리뷰 효율(증분 diff, 테스트 재실행 안내), 재현 테스트, 실시간 작업 보기."""

from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

import pytest

from duet.activity import call_start_epoch, claude_activity, claude_project_dir, codex_activity
from duet.agents.mock import MockAdapter
from duet.phases.build import BuildPhase
from duet.repro import parse_repros
from duet.workspace import Workspace
from tests.helpers import file_names, make_ctx, py_cmd

# 재현 테스트(파이썬 스크립트)를 모두 돌리는 테스트 명령. sh·cmd.exe 어디서나 돈다 (DESIGN.md 27.7)
REPRO_TEST_CMD = py_cmd("import glob, subprocess, sys; "
                        "rc = max([subprocess.call([sys.executable, f]) for f in sorted(glob.glob('tests/test_repro_*.py'))] or [0]); "
                        "print('all-ok' if rc == 0 else 'fail'); sys.exit(rc)")


# ====================================================================== 재현 테스트 파싱
def test_parse_repros_accepts_and_rejects(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_existing.py").write_text("x")
    text = """
<repro path="tests/test_repro_ok.py">
```python
def test_x():
    assert 1 == 2
```
</repro>
<repro path="../evil_test.py">x</repro>
<repro path="/etc/test_abs.py">x</repro>
<repro path=".duet/test_x.py">x</repro>
<repro path="tests/test_existing.py">x</repro>
<repro path="src/main.py">x</repro>
<repro path='spec/repro_case.sh'>exit 1</repro>
"""
    r = parse_repros(text, tmp_path)
    assert [f.path for f in r.files] == ["tests/test_repro_ok.py", "spec/repro_case.sh"]
    assert r.files[0].content == "def test_x():\n    assert 1 == 2\n"     # 코드 펜스를 벗김
    assert len(r.rejected) == 5
    assert any("새 파일만" in x for x in r.rejected) and any("테스트 파일로" in x for x in r.rejected)


def test_parse_repros_limits(tmp_path: Path):
    many = "".join(f'<repro path="tests/test_r{i}.py">x</repro>' for i in range(7))
    r = parse_repros(many, tmp_path)
    assert len(r.files) == 5 and len(r.rejected) == 2
    big = f'<repro path="tests/test_big.py">{"x" * 30000}</repro>'
    assert parse_repros(big, tmp_path).rejected


# ====================================================================== build 통합
def test_repro_flow_end_to_end(tmp_path: Path):
    prompts = {"review": [], "fix": []}

    def impl(req, n):
        if req.step == "fix":
            prompts["fix"].append(req.prompt)
            (req.cwd / "tests" / "test_repro_empty.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")   # 고쳤다고 치고
        (req.cwd / "tests").mkdir(exist_ok=True)
        (req.cwd / "main.py").write_text(f"v{n}\n", encoding="utf-8")
        return "done"

    def rev(req, n):
        prompts["review"].append(req.prompt)
        if n == 1:
            return ("## 반드시 고칠 것\n- [P2] 빈 입력에서 실패\n\n"
                    '<repro path="tests/test_repro_empty.py">\necho "빈 입력 실패"; exit 1\n</repro>\n'
                    "<verdict>\nstatus: CHANGES_REQUESTED\nmust_fix: 1\np1: 0\np2: 1\np3: 0\n</verdict>")
        return "<verdict>\nstatus: APPROVED\nmust_fix: 0\np1: 0\np2: 0\np3: 0\n</verdict>"

    ctx = make_ctx(tmp_path, agents={"claude": MockAdapter(label="claude", responder=impl),
                                     "codex": MockAdapter(label="codex", responder=rev)},
                   overrides={"test_command": REPRO_TEST_CMD})
    (tmp_path / "DESIGN.md").write_text("# d\n", encoding="utf-8")
    assert BuildPhase(ctx).run() is True
    st = ctx.state
    r = st.repros["1"]
    assert r["files"] == ["tests/test_repro_empty.py"] and r["status"] == "failed" and r["commit"]
    assert file_names(ctx.run_dir) == ["01_impl1_claude.md", "02_test1.md", "03_review1_codex.md", "04_repro1.md",
                                       "05_impl2_claude.md", "06_test2.md", "07_testguard2.md", "08_review2_codex.md"]
    # 구현자가 재현 테스트를 'exit 0' 으로 바꿨다 → 테스트 변경 경고 (DESIGN.md 24.1)
    assert [s["kind"] for s in st.test_guard["2"]["signals"]] == ["repro_changed"]
    assert "리뷰어 재현 테스트 변경: `tests/test_repro_empty.py`" in prompts["review"][1]
    assert "재현됨" in (ctx.run_dir / "04_repro1.md").read_text(encoding="utf-8")
    # 리뷰 프롬프트: 재현 테스트 안내, 테스트 재실행 하지 말라는 안내
    assert "tests/test_repro_" in prompts["review"][0] and "다시 돌리지 마라" in prompts["review"][0]
    # 수정 프롬프트에 재현 테스트가 들어감
    assert "tests/test_repro_empty.py" in prompts["fix"][0] and "재현됨" in prompts["fix"][0]
    # 다음 라운드 테스트는 재현 테스트까지 돌려 통과
    assert st.tests["2"]["status"] == "passed"
    log = Workspace(tmp_path).git("log", "--format=%s")
    assert "duet: repro tests from review 1" in log
    assert st.is_done("repro:1")


def test_repro_rejected_and_disabled(tmp_path: Path):
    rev_text = ('<repro path="../outside_test.py">x</repro>\n'
                "<verdict>\nstatus: CHANGES_REQUESTED\nmust_fix: 1\np1: 0\np2: 1\np3: 0\n</verdict>")
    ctx = make_ctx(tmp_path, agents={"claude": MockAdapter(label="claude"),
                                     "codex": MockAdapter(label="codex", responder=lambda r, n: rev_text)},
                   overrides={"max_review": 1, "stall_rounds": 0})
    (tmp_path / "DESIGN.md").write_text("# d\n", encoding="utf-8")
    BuildPhase(ctx).run()
    assert ctx.state.repros["1"]["files"] == [] and ctx.state.repros["1"]["rejected"]
    assert not (tmp_path.parent / "outside_test.py").exists()

    wd2 = tmp_path / "b"
    ctx2 = make_ctx(wd2, agents={"claude": MockAdapter(label="claude"),
                                 "codex": MockAdapter(label="codex", responder=lambda r, n: '<repro path="tests/test_a.py">x</repro>' + rev_text)},
                    overrides={"max_review": 1, "repro_tests": False, "stall_rounds": 0})
    (wd2 / "DESIGN.md").write_text("# d\n", encoding="utf-8")
    prompts = []
    ctx2.agents["codex"].responder = lambda r, n: (prompts.append(r.prompt), rev_text)[1]
    BuildPhase(ctx2).run()
    assert ctx2.state.repros == {} and not (wd2 / "tests" / "test_a.py").exists()
    assert "<repro path" not in prompts[0]


def test_incremental_diff_falls_back_to_commit_message(tmp_path: Path):
    """예전 실행(리뷰 시점 커밋 기록 없음)도 'duet: impl round N' 커밋으로 증분 diff 기준을 찾는다."""
    prompts = []

    def impl(req, n):
        (req.cwd / "main.py").write_text(f"v{n}\n", encoding="utf-8")
        return "done"

    def rev(req, n):
        prompts.append(req.prompt)
        return "<verdict>\nstatus: CHANGES_REQUESTED\nmust_fix: 1\n</verdict>" if n == 1 else "<verdict>\nstatus: APPROVED\nmust_fix: 0\n</verdict>"

    ctx = make_ctx(tmp_path, agents={"claude": MockAdapter(label="claude", responder=impl),
                                     "codex": MockAdapter(label="codex", responder=rev)})
    (tmp_path / "DESIGN.md").write_text("# d\n", encoding="utf-8")
    phase = BuildPhase(ctx)
    orig = phase._review_diff

    def without_record(i, base):
        ctx.state.reviewed_commits.clear()
        return orig(i, base)

    phase._review_diff = without_record
    assert phase.run()
    assert "[지난 리뷰 이후 바뀐 부분 (diff)]" in prompts[1] and "-v1" in prompts[1]


# ====================================================================== 실시간 작업 보기
def _iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat().replace("+00:00", "Z")


def test_claude_activity(tmp_path: Path):
    wd = tmp_path / "my proj.v2"
    wd.mkdir()
    d = claude_project_dir(wd, tmp_path)
    import re as _re
    assert d.name == _re.sub(r"[^A-Za-z0-9]", "-", str(wd.resolve()))
    d.mkdir(parents=True)
    now = time.time()
    lines = [
        {"type": "assistant", "timestamp": _iso(now - 3600), "message": {"content": [{"type": "text", "text": "옛날 것"}]}},
        {"type": "assistant", "timestamp": _iso(now - 5), "message": {"content": [
            {"type": "text", "text": "파일을 읽겠습니다."},
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/x/core.py"}},
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/x/core.py"}},
            {"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q", "description": "테스트"}},
            {"type": "tool_use", "name": "Grep", "input": {"pattern": "def ", "path": "src"}},
            {"type": "thinking", "thinking": "..."}]}},
        {"type": "user", "timestamp": _iso(now - 4), "message": {"content": [{"type": "tool_result"}]}},
    ]
    (d / "s.jsonl").write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    ev = claude_activity(wd, now - 60, tmp_path)
    assert [(e["kind"], e["text"]) for e in ev] == [
        ("message", "파일을 읽겠습니다."), ("read", "/x/core.py"), ("edit", "/x/core.py"),
        ("command", "pytest -q"), ("search", "Grep def")]
    assert ev[3]["detail"] == "테스트"
    assert claude_activity(tmp_path / "other", now - 60, tmp_path) == []


def test_codex_activity(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    wd = tmp_path / "wd"
    wd.mkdir()
    now = time.time()
    day = dt.date.today()
    folder = tmp_path / "codex" / "sessions" / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"
    folder.mkdir(parents=True)
    events = [
        {"timestamp": _iso(now - 10), "type": "session_meta", "payload": {"cwd": str(wd.resolve())}},
        {"timestamp": _iso(now - 9), "type": "response_item", "payload": {"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "설계 문서를 먼저 읽겠습니다."}]}},
        {"timestamp": _iso(now - 8), "type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
            "input": 'await tools.exec_command({cmd:"cat DESIGN.md",max_output_tokens:1000}); tools.exec_command({cmd:"rg \\"def x\\" src"})'}},
        {"timestamp": _iso(now - 7), "type": "response_item", "payload": {"type": "custom_tool_call", "name": "apply_patch",
            "input": "*** Begin Patch\n*** Update File: src/a.py\n@@\n-x\n+y\n*** Add File: tests/test_b.py\n*** End Patch"}},
        {"timestamp": _iso(now - 6), "type": "response_item", "payload": {"type": "function_call", "name": "shell",
            "arguments": json.dumps({"command": ["bash", "-lc", "pytest -q"]})}},
    ]
    (folder / "rollout-x.jsonl").write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    ev = codex_activity(wd, now - 60)
    assert [(e["kind"], e["text"]) for e in ev] == [
        ("message", "설계 문서를 먼저 읽겠습니다."), ("command", "cat DESIGN.md"), ("command", 'rg "def x" src'),
        ("edit", "src/a.py"), ("edit", "tests/test_b.py"), ("command", "pytest -q")]
    assert codex_activity(tmp_path / "other", now - 60) == []
    assert codex_activity(wd, now + 60) == []


def test_call_start_epoch_handles_midnight():
    now = dt.datetime(2026, 10, 16, 0, 0, 30)
    assert call_start_epoch("23:59:30", now) == dt.datetime(2026, 10, 15, 23, 59, 30).timestamp()
    assert call_start_epoch("00:00:10", now) == dt.datetime(2026, 10, 16, 0, 0, 10).timestamp()


def test_claude_activity_finds_session_by_cwd_when_folder_name_differs(tmp_path: Path):
    wd = tmp_path / "proj_x"
    wd.mkdir()
    other = tmp_path / "projects" / "some-other-naming"
    other.mkdir(parents=True)
    now = time.time()
    lines = [{"type": "user", "cwd": str(wd.resolve()), "timestamp": _iso(now - 3)},
             {"type": "assistant", "cwd": str(wd.resolve()), "timestamp": _iso(now - 2),
              "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "a.py"}}]}}]
    (other / "s.jsonl").write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    assert [e["text"] for e in claude_activity(wd, now - 60, tmp_path)] == ["a.py"]
