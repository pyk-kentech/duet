"""M26: 결과 요약 (DESIGN.md 32장). 실제 claude/codex 는 부르지 않는다(mock)."""

from __future__ import annotations

from pathlib import Path

import pytest

import tenure.orchestrator as orch_mod
from tenure.agents.mock import MockAdapter
from tenure.cli import main
from tenure.config import Config, ConfigError, load_config
from tenure.options import BY_KEY
from tenure.report import REPORT_ROLE
from tenure.state import RunState, list_run_dirs
from tenure.transcript import Transcript
from tenure.ui.dashboard import ApiError, Dashboard


def run(tmp_path: Path, *extra: str, name: str = "w") -> tuple[int, RunState, Path]:
    wd = tmp_path / name
    rc = main(["run", "메모 CLI", "--workdir", str(wd), "--mock", "--debate-rounds", "0", *extra])
    [rd] = list_run_dirs(wd)
    return rc, RunState.load(rd), rd


def report_entries(rd: Path):
    return [e for e in Transcript(rd).entries() if e.meta.get("step") == "report"]


def test_report_after_approved_run(tmp_path: Path):
    rc, st, rd = run(tmp_path)
    assert rc == 0 and st.status == "done_approved" and st.phase == "done"
    assert st.report and "report" in st.done
    [e] = report_entries(rd)
    assert e.name == st.report and e.name.endswith("_report_claude.md")
    assert "## 실행 방법" in e.path.read_text(encoding="utf-8")
    call = st.calls[-1]
    assert (call.step, call.agent) == ("report", "claude")              # 기록·사용량은 CLI 기준
    assert st.config["report_model"] == "claude-haiku-5-5"
    assert "결과 요약 →" in (rd / "console.log").read_text(encoding="utf-8")


def test_report_off_and_design_only(tmp_path: Path):
    rc, st, rd = run(tmp_path, "--set", "report=false", name="off")
    assert rc == 0 and st.report is None and not report_entries(rd)
    rc, st, rd = run(tmp_path, "--design-only", name="design")
    assert st.status == "done_design" and st.report is None and not report_entries(rd)


def test_report_after_unapproved_run_mentions_outcome(tmp_path: Path, monkeypatch):
    seen = {}

    def factory(cfg, *, mock):
        return {"claude": MockAdapter(label="claude"), "codex": MockAdapter(label="codex", approve_on_review=99)}

    monkeypatch.setattr(orch_mod, "make_agents", factory)
    real = orch_mod.MockAdapter

    class Spy(real):
        def ask(self, req):
            if req.step == "report":
                seen["prompt"] = req.prompt
            return super().ask(req)

    monkeypatch.setattr(orch_mod, "MockAdapter", Spy)
    rc, st, rd = run(tmp_path, "--max-review", "1")
    assert st.status == "done_unapproved" and st.report
    assert "미승인" in seen["prompt"] and "마지막 리뷰 기록" in seen["prompt"] and "메모 CLI" in seen["prompt"]


@pytest.mark.parametrize("kind", ["fail", "rate_limit"])
def test_report_failure_keeps_result(tmp_path: Path, monkeypatch, kind):
    real = orch_mod.MockAdapter

    def make(label="mock", **kw):
        if label == REPORT_ROLE:
            kw["fail_on_calls" if kind == "fail" else "rate_limit_on_calls"] = {1, 2}     # 실패는 한 번 다시 시도한다
        return real(label=label, **kw)

    monkeypatch.setattr(orch_mod, "MockAdapter", make)
    rc, st, rd = run(tmp_path)
    assert rc == 0 and st.status == "done_approved" and st.phase == "done" and st.error is None
    assert st.report is None and "report" in st.done                    # 다시 부르지 않는다
    log = (rd / "console.log").read_text(encoding="utf-8")
    assert "결과 요약을 만들지 못했습니다" in log or "결과 요약을 건너뜀" in log


def test_duet_report_command(tmp_path: Path, capsys):
    rc, st, rd = run(tmp_path)
    first = st.report
    capsys.readouterr()
    assert main(["report", "--workdir", str(tmp_path / "w")]) == 0
    out = capsys.readouterr().out
    assert "## 만든 것" in out and "기록:" in out
    st2 = RunState.load(rd)
    assert st2.report and st2.report != first and st2.status == "done_approved"
    assert len(report_entries(rd)) == 2
    rc, st, rd = run(tmp_path, "--design-only", name="d")
    assert main(["report", "--workdir", str(tmp_path / "d")]) != 0          # 끝난(승인·미승인) 실행만


def test_dashboard_make_report(tmp_path: Path, monkeypatch):
    rc, st, rd = run(tmp_path)
    seen = {}
    monkeypatch.setattr(Dashboard, "_spawn", lambda self, kind, wd, argv: seen.update(kind=kind, argv=argv) or {"id": "j"})
    d = Dashboard(extra_projects=[str(tmp_path / "w")]) if "extra_projects" in Dashboard.__init__.__code__.co_varnames \
        else Dashboard()
    from tenure.registry import Registry

    Registry().add(tmp_path / "w")
    d.make_report({"project": str(tmp_path / "w"), "run": rd.name})
    assert seen["kind"] == "report"
    assert seen["argv"][:2] == ["report", "--workdir"] and seen["argv"][-3:] == ["--run", rd.name, "--mock"]
    rc, st, rd2 = run(tmp_path, "--design-only", name="d")
    Registry().add(tmp_path / "d")
    with pytest.raises(ApiError, match="끝난 실행만"):
        d.make_report({"project": str(tmp_path / "d"), "run": rd2.name})


def test_report_settings():
    cfg = Config()
    assert (cfg.report, cfg.report_agent, cfg.report_model) == (True, "claude", "claude-haiku-5-5")
    assert {"report", "report_agent", "report_model", "report_effort"} <= set(BY_KEY)
    with pytest.raises(ConfigError, match="report_agent"):
        load_config(None, {"report_agent": "gpt"})
    with pytest.raises(ConfigError, match="report_model"):
        load_config(None, {"report_model": "a b"})
