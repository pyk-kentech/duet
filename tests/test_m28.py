"""M28: 혼자 기준선 solo-claude·solo-codex (DESIGN.md 34장). 실제 claude/codex 는 부르지 않는다(mock)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import tenure.orchestrator as orch_mod
from tenure import limits
from tenure.agents.base import Mode
from tenure.agents.mock import MockAdapter
from tenure.bench import (
    RESULTS_JSON,
    SOLO_DESIGN_NOTE,
    SOLO_INSTRUCTION,
    SUMMARY_MD,
    Task,
    load_results,
    run_bench,
    solo_prompt,
    workflow_stats,
)
from tenure.cli import main
from tests.test_bench import make_suite

PYTEST = [sys.executable, "-m", "pytest"]


def _agents(monkeypatch, **kw) -> dict:
    made: dict = {}

    def factory(cfg, *, mock):
        made["claude"] = MockAdapter(label="claude", **kw.get("claude", {}))
        made["codex"] = MockAdapter(label="codex", **kw.get("codex", {}))
        return dict(made)

    monkeypatch.setattr(orch_mod, "make_agents", factory)
    return made


def test_solo_and_classic_in_one_bench(tmp_path: Path, monkeypatch):
    suite = make_suite(tmp_path)
    made = _agents(monkeypatch)
    lines: list[str] = []
    rd = run_bench(suite=str(suite), workflows=["solo-claude", "solo-codex", "classic"], task_names=["hello"],
                   out_root=tmp_path / "out", mock=True, printer=lines.append, pytest_cmd=PYTEST)
    rows = {r["workflow"]: r for r in load_results(rd)["rows"]}
    solo = rows["solo-claude"]
    assert solo["status"] == "solo" and solo["solo"] and not solo["approved"] and solo["rounds"] == 0
    assert solo["calls"] == 1 and set(solo["usage"]) == {"claude"} and solo["hidden"]["all_passed"]
    assert rows["solo-codex"]["status"] == "solo" and set(rows["solo-codex"]["usage"]) == {"codex"}
    assert rows["classic"]["status"] == "approved" and not rows["classic"].get("solo")
    # 그 CLI 를 구현 자리처럼 한 번: 쓰기 모드, implement 단계, 과제 + 지시
    wd = Path(solo["workdir"])
    assert (wd / ".tenure" / "solo" / "answer.md").is_file()
    assert json.loads((wd / ".tenure" / "solo" / "call.json").read_text(encoding="utf-8"))["exit_code"] == 0
    assert not (wd / ".tenure" / "runs").exists()                              # tenure 실행이 아니다
    summary = (rd / SUMMARY_MD).read_text(encoding="utf-8")
    assert "| solo-claude | 1 | - | - | 100% (1개 채점) | 1/1 | - |" in summary
    assert "| classic | 1 | 1/1 |" in summary
    assert any("hello × solo-claude #1: 혼자 완료, 숨은 테스트 2/2" in ln for ln in lines)
    stats = {s["workflow"]: s for s in workflow_stats(load_results(rd)["rows"])}
    assert stats["solo-codex"]["solo"] and not stats["classic"]["solo"]


def test_solo_request_matches_implementer_seat(tmp_path: Path, monkeypatch):
    suite = make_suite(tmp_path)
    (suite / "hello" / "bench.toml").write_text('name = "hello"\nkind = "new"\ntimeout_sec = 1234\n', encoding="utf-8")
    made = _agents(monkeypatch)
    run_bench(suite=str(suite), workflows=["solo-codex"], task_names=["hello"], out_root=tmp_path / "out",
              mock=True, printer=lambda s: None, pytest_cmd=PYTEST)
    [req] = made["codex"].calls
    assert not made["claude"].calls
    assert req.mode is Mode.WRITE and req.step == "implement" and req.timeout_sec == 1234
    assert req.prompt.startswith("main.py 를 만든다") and req.prompt.endswith(SOLO_INSTRUCTION)


def test_solo_prompt_with_fixed_design(tmp_path: Path):
    (tmp_path / "task.md").write_text("과제 본문", encoding="utf-8")
    task = Task("t", "", "new", tmp_path)
    assert SOLO_DESIGN_NOTE in solo_prompt(task, fixed_design=True)
    assert SOLO_DESIGN_NOTE not in solo_prompt(task)


def test_solo_rate_limit_stops_bench(tmp_path: Path, monkeypatch):
    suite = make_suite(tmp_path)
    _agents(monkeypatch, claude={"rate_limit_on_calls": {1}})
    lines: list[str] = []
    rd = run_bench(suite=str(suite), workflows=["solo-claude", "classic"], out_root=tmp_path / "out", mock=True,
                   printer=lines.append, pytest_cmd=PYTEST)
    rows = load_results(rd)["rows"]
    assert len(rows) == 1 and rows[0]["status"] == "stopped" and rows[0]["hidden"] is None
    assert any("벤치마크를 멈춥니다" in ln for ln in lines)


def test_solo_waits_on_limit_and_resends(tmp_path: Path, monkeypatch):
    suite = make_suite(tmp_path)
    made = _agents(monkeypatch, claude={"rate_limit_on_calls": {1}})
    slept: list[float] = []
    monkeypatch.setattr(limits, "sleep", slept.append)
    lines: list[str] = []
    rd = run_bench(suite=str(suite), workflows=["solo-claude"], task_names=["hello"], out_root=tmp_path / "out",
                   mock=True, printer=lines.append, pytest_cmd=PYTEST, wait_on_limit=True)
    [row] = load_results(rd)["rows"]
    assert row["status"] == "solo" and row["calls"] == 2 and len(made["claude"].calls) == 2
    assert slept and row["limit_wait_sec"] == round(slept[0], 1) and row["hidden"]["all_passed"]
    assert any("한도 도달" in ln and "다시 보냅니다" in ln for ln in lines)


def test_solo_failure_is_not_graded(tmp_path: Path, monkeypatch):
    suite = make_suite(tmp_path)
    _agents(monkeypatch, codex={"fail_on_calls": {1}})
    rd = run_bench(suite=str(suite), workflows=["solo-codex"], task_names=["hello"], out_root=tmp_path / "out",
                   mock=True, printer=lambda s: None, pytest_cmd=PYTEST)
    [row] = load_results(rd)["rows"]
    assert row["status"] == "failed" and row["hidden"] is None and row["error"]


def test_cli_bench_mock_with_solo(tmp_path: Path, capsys):
    suite = make_suite(tmp_path)
    code = main(["bench", "run", "--suite", str(suite), "--task", "hello", "--workflow", "solo-claude",
                 "--workflow", "classic", "--mock", "--out", str(tmp_path / "out")])
    assert code == 0
    [rd] = list((tmp_path / "out").iterdir())
    assert {r["workflow"] for r in json.loads((rd / RESULTS_JSON).read_text(encoding="utf-8"))["rows"]} == {
        "solo-claude", "classic"}
