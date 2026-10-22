"""최적화 1차 (DESIGN.md 36.16): 결과 요약 자료 미리 모으기, 사용량 집계 캐시."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from tenure import usage
from tenure.config import load_config
from tenure.phases.common import PhaseContext
from tenure.report import gather_context
from tenure.state import DONE_APPROVED, DONE_UNAPPROVED, RunState
from tenure.transcript import Transcript
from tenure.workspace import Workspace


def project(tmp_path: Path) -> Path:
    wd = tmp_path / "p"
    wd.mkdir()
    (wd / "README.md").write_text("# 할일\n\n`python main.py add 우유` 로 추가한다.\n", encoding="utf-8")
    (wd / "package.json").write_text(json.dumps({"name": "todo", "scripts": {"start": "node index.js"},
                                                 "dependencies": {"x": "1"}}), encoding="utf-8")
    (wd / "pyproject.toml").write_text('[project]\nname = "todo"\n[project.scripts]\ntodo = "todo:main"\n', encoding="utf-8")
    (wd / "Makefile").write_text("run:\n\tpython main.py\ntest:\n\tpytest\nX := 1\n", encoding="utf-8")
    (wd / "tenure.toml").write_text('test_command = "python -m pytest -q"\n', encoding="utf-8")
    (wd / "IMPLEMENTATION_NOTES.md").write_text("- 날짜는 ISO 로 받는다\n", encoding="utf-8")
    (wd / "main.py").write_text("print('hi')\n", encoding="utf-8")
    ws = Workspace(wd)
    ws.git("init", "-q")
    ws.git("add", "-A")
    ws.git("commit", "-q", "-m", "init")
    return wd


def ctx_for(wd: Path, status: str, review: str | None = None) -> PhaseContext:
    rd = wd / ".tenure" / "runs" / "r1"
    rd.mkdir(parents=True)
    st = RunState(run_id="r1", task="할일 CLI", config={})
    st.status = status
    tr = Transcript(rd)
    if review:
        st.last_review = tr.save("review1_codex", review, {"step": "review"}).name
    return PhaseContext(task=st.task, workdir=wd, cfg=load_config(None), agents={}, state=st, transcript=tr, run_dir=rd)


def test_gather_context_collects_run_hints(tmp_path):
    wd = project(tmp_path)
    text = gather_context(ctx_for(wd, DONE_APPROVED), Workspace(wd))
    assert "[파일 목록]" in text and "main.py" in text and "README.md" in text
    assert '"start": "node index.js"' in text and "dependencies" not in text.split("package.json:")[1].split("\n")[0]
    assert '"todo": "todo:main"' in text
    assert "Makefile 대상: run, test" in text
    assert 'tenure.toml: test_command = "python -m pytest -q"' in text
    assert "진입점 후보: main.py" in text
    assert "python main.py add 우유" in text and "날짜는 ISO" in text
    assert "반드시 고칠 것" not in text                     # 승인이면 리뷰 지적은 넣지 않는다


def test_gather_context_includes_must_fix_when_unapproved(tmp_path):
    wd = project(tmp_path)
    review = "## 반드시 고칠 것\n- [P2] 빈 제목을 거부하지 않음\n\n## 참고\n- 이름\n"
    text = gather_context(ctx_for(wd, DONE_UNAPPROVED, review), Workspace(wd))
    assert "[마지막 리뷰의 반드시 고칠 것]" in text and "빈 제목을 거부하지 않음" in text and "## 참고" not in text


def test_gather_context_caps_large_inputs(tmp_path):
    wd = project(tmp_path)
    (wd / "README.md").write_text("가" * 10_000, encoding="utf-8")
    for i in range(150):
        (wd / f"f{i:03}.txt").write_text("x", encoding="utf-8")
    Workspace(wd).git("add", "-A")
    text = gather_context(ctx_for(wd, DONE_APPROVED), Workspace(wd))
    assert "외 " in text and text.count("가") <= 3_000 and "(생략)" in text


# ------------------------------------------------------------------ usage cache
def _line(rid: str, ts: dt.datetime, inp: int, out: int) -> str:
    return json.dumps({"requestId": rid, "timestamp": ts.isoformat().replace("+00:00", "Z"),
                       "message": {"model": "claude-opus-5-5", "usage": {"input_tokens": inp, "output_tokens": out}}}) + "\n"


def test_claude_usage_cache_reads_only_appended(tmp_path, monkeypatch):
    usage._RECORDS.clear()
    now = dt.datetime.now(dt.timezone.utc)
    f = tmp_path / "projects" / "x" / "s.jsonl"
    f.parent.mkdir(parents=True)
    f.write_text(_line("a", now, 10, 1) + '{"type": "user"}\n' + _line("a", now, 10, 1), encoding="utf-8")
    first = usage.claude_local_usage(now, home=tmp_path)
    five = next(iter(first["windows"].values()))
    assert five["input_tokens"] == 10 and five["messages"] == 1           # 같은 요청 키는 한 번
    calls = []
    real_loads = json.loads
    monkeypatch.setattr(usage.json, "loads", lambda s, *a, **k: calls.append(1) or real_loads(s, *a, **k))
    usage.claude_local_usage(now, home=tmp_path)
    assert calls == []                                                    # 그대로면 다시 파싱하지 않음
    with f.open("a", encoding="utf-8") as fh:
        fh.write(_line("b", now, 5, 2) + _line("c", now, 7, 0)[:-10])      # 마지막 줄은 아직 쓰는 중
    os.utime(f, (now.timestamp() + 5, now.timestamp() + 5))
    second = usage.claude_local_usage(now, home=tmp_path)
    assert next(iter(second["windows"].values()))["input_tokens"] == 15 and len(calls) == 1
    with f.open("a", encoding="utf-8") as fh:
        fh.write(_line("c", now, 7, 0)[-10:])
    os.utime(f, (now.timestamp() + 9, now.timestamp() + 9))
    third = usage.claude_local_usage(now, home=tmp_path)
    assert next(iter(third["windows"].values()))["input_tokens"] == 22
    assert third["output_by_model_7d"] == {"claude-opus-5-5": 3}


def test_claude_usage_cache_resets_when_file_shrinks(tmp_path):
    usage._RECORDS.clear()
    now = dt.datetime.now(dt.timezone.utc)
    f = tmp_path / "projects" / "x" / "s.jsonl"
    f.parent.mkdir(parents=True)
    f.write_text(_line("a", now, 10, 1) + _line("b", now, 10, 1), encoding="utf-8")
    usage.claude_local_usage(now, home=tmp_path)
    f.write_text(_line("z", now, 3, 0), encoding="utf-8")
    os.utime(f, (now.timestamp() + 5, now.timestamp() + 5))
    assert next(iter(usage.claude_local_usage(now, home=tmp_path)["windows"].values()))["input_tokens"] == 3
