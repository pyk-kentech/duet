"""M19: 한도 대기 후 자동 재개 + 요구 근거 관문 (DESIGN.md 25장)."""

from __future__ import annotations

import datetime as dt
import json

import pytest

import duet.orchestrator as orch_mod
from duet import gates, limits
from duet.agents.mock import MockAdapter
from duet.arbiter import format_issues
from duet.bench import run_bench
from duet.cli import main
from duet.config import ConfigError, load_config
from duet.review_json import REVIEW_SCHEMA, output_instruction, render_review
from duet.state import RunState, list_run_dirs

NOW = dt.datetime(2026, 10, 16, 10, 0, tzinfo=dt.timezone.utc).timestamp()


# ====================================================================== 재개 시각 (25.1)
def test_reset_from_epoch_and_relative():
    assert limits.reset_from_text([f"Claude AI usage limit reached|{int(NOW) + 3600}"], NOW) == NOW + 3600
    assert limits.reset_from_text([f'{{"resets_at": {int(NOW) + 60}}}'], NOW) == NOW + 60
    assert limits.reset_from_text(["You've hit your usage limit. Try again in 2 hours 5 minutes."], NOW) == NOW + 7500
    assert limits.reset_from_text(["limit; resets in 37m"], NOW) == NOW + 37 * 60
    assert limits.reset_from_text(["try again in 1 day, 2 hours and 3 minutes"], NOW) == NOW + 86400 + 7200 + 180
    assert limits.reset_from_text([f"limit reached|{int(NOW) + 30 * 86400}"], NOW) is None     # 너무 먼 시각


def test_reset_from_clock():
    assert limits.reset_from_text(["5-hour limit reached ∙ resets 3pm (UTC)"], NOW) == NOW + 5 * 3600
    later = NOW + 6 * 3600                                    # 16:00 UTC → 다음 날 15:00
    assert limits.reset_from_text(["resets 3pm (UTC)"], later) == NOW + 29 * 3600
    assert limits.reset_from_text(["try again at 10:30 (UTC)"], NOW) == NOW + 1800
    assert limits.reset_from_text(["reset at 5"], NOW) is None   # 숫자만이면 시각인지 모름
    local = limits.reset_from_text(["try again at 3:05 PM"], NOW)
    assert local is not None and NOW < local <= NOW + 86400 and dt.datetime.fromtimestamp(local).minute == 5


def test_reset_from_usage_and_plan():
    usage = {"rate_limits": {"primary": {"used_percent": 100.0, "resets_at": NOW + 600},
                             "secondary": {"used_percent": 40.0, "resets_at": NOW + 9000}}}
    assert limits.reset_from_usage(usage, NOW) == NOW + 600
    assert limits.reset_from_usage({"rate_limits": {"primary": {"used_percent": 50, "resets_at": NOW + 5}}}, NOW) is None
    assert limits.plan_wait(["try again in 10 minutes"], None, 1, NOW) == (660, "메시지의 재개 시각")
    assert limits.plan_wait([""], usage, 1, NOW) == (660, "사용량 기록의 재개 시각")
    assert [limits.plan_wait(["usage limit"], None, h, NOW)[0] for h in (1, 2, 3, 4)] == [900, 1800, 3600, 3600]
    assert limits.plan_wait(["try again in 5 seconds"], None, 1, NOW)[0] == 65


def test_config_validation(tmp_path):
    (tmp_path / "duet.toml").write_text("limit_wait_max_min = 0\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="limit_wait_max_min"):
        load_config(tmp_path, global_defaults={})
    (tmp_path / "duet.toml").write_text("wait_on_limit = true\nlimit_wait_max_min = 30\n", encoding="utf-8")
    cfg = load_config(tmp_path, global_defaults={})
    assert cfg.wait_on_limit is True and cfg.limit_wait_max_min == 30


# ====================================================================== 대기 후 재시도 (25.1)
def run(tmp_path, monkeypatch, *extra, claude=None, codex=None, toml="", sleep=None):
    seen: dict = {}
    waits: list[float] = []

    def factory(cfg, *, mock):
        seen["claude"] = claude or MockAdapter(label="claude")
        seen["codex"] = codex or MockAdapter(label="codex")
        return dict(seen)

    monkeypatch.setattr(orch_mod, "make_agents", factory)
    monkeypatch.setattr(limits, "sleep", sleep or waits.append)
    wd = tmp_path / "w"
    wd.mkdir(parents=True)
    (wd / "duet.toml").write_text('test_command = "none"\n' + toml, encoding="utf-8")
    rc = main(["run", "t", "--workdir", str(wd), "--mock", "--debate-rounds", "0", *extra])
    [rd] = list_run_dirs(wd)
    return rc, seen, RunState.load(rd), waits


def test_waits_and_retries_same_call(tmp_path, monkeypatch, capsys):
    claude = MockAdapter(label="claude", rate_limit_on_calls={2})       # 2번째 호출 = 구현
    rc, seen, st, waits = run(tmp_path, monkeypatch, "--wait-on-limit", claude=claude)
    assert rc == 0 and st.status == "done_approved" and waits == [900.0]
    assert st.limit_waited_sec == 900 and st.limit_wait is None and st.config["wait_on_limit"] is True
    impl = [c for c in st.calls if c.step == "implement"]
    assert [c.rate_limited for c in impl] == [True, False]
    out = capsys.readouterr().out
    assert "⏳ claude 한도 도달 (implement)" in out and "15분 뒤 다시 시도" in out


def test_without_flag_stops_as_before(tmp_path, monkeypatch):
    rc, _, st, waits = run(tmp_path, monkeypatch, claude=MockAdapter(label="claude", rate_limit_on_calls={2}))
    assert st.status == "stopped_rate_limit" and waits == [] and st.limit_waited_sec == 0


def test_wait_budget_runs_out(tmp_path, monkeypatch, capsys):
    claude = MockAdapter(label="claude", rate_limit_on_calls={2, 3})
    rc, _, st, waits = run(tmp_path, monkeypatch, "--wait-on-limit", claude=claude, toml="limit_wait_max_min = 10\n")
    assert st.status == "stopped_rate_limit" and waits == [600.0] and st.limit_waited_sec == 600
    assert "한도 대기 예산(10분)을 다 써서 멈춥니다" in capsys.readouterr().out


def test_stop_while_waiting(tmp_path, monkeypatch):
    def interrupted(sec):
        raise KeyboardInterrupt

    rc, _, st, _ = run(tmp_path, monkeypatch, "--wait-on-limit", claude=MockAdapter(label="claude", rate_limit_on_calls={2}),
                       sleep=interrupted)
    assert st.status == "stopped_user" and st.limit_wait is None


def test_bench_passes_wait_on_limit(tmp_path, monkeypatch):
    seen = []
    real = orch_mod.Orchestrator.run

    def spy(self, opts):
        seen.append(opts.overrides.get("wait_on_limit"))
        return real(self, opts)

    monkeypatch.setattr(orch_mod.Orchestrator, "run", spy)
    out = run_bench(task_names=["roman"], out_root=tmp_path, mock=True, printer=lambda s: None, wait_on_limit=True)
    meta = json.loads((out / "results.json").read_text(encoding="utf-8"))["meta"]
    assert seen == [True] and meta["wait_on_limit"] is True


# ====================================================================== 요구 근거 관문 (25.2)
SPEC = "할 일 CLI.\n## 요구\n- `add` 는 빈 제목을 거부하고, 종료 코드 2 로 끝낸다.\n- 목록은 생성 순서대로 출력한다."


def f(basis, req="", sev="P2", fid="", evidence="main.py:3 확인"):
    return {"id": fid, "severity": sev, "new": True, "title": f"{basis} 지적", "file": "main.py", "detail": "d",
            "evidence": evidence, "basis": basis, "requirement": req}


def apply(*findings, spec=SPEC):
    return gates.apply_gates({"status": "CHANGES_REQUESTED", "summary": "", "findings": list(findings), "repro": []},
                             round_=1, open_ids=set(), changed_files=None, first_number=1, spec_text=spec)


def test_quote_found():
    assert gates.quote_found("add 는 빈 제목을 거부하고, 종료 코드 2로 끝낸다", SPEC)          # 띄어쓰기·구두점 무시
    assert gates.quote_found("`ADD` 는 빈 제목을 거부 ... 생성 순서대로 출력", SPEC)           # 조각마다
    assert not gates.quote_found("Python 3.8 과 호환되어야 한다", SPEC)
    assert not gates.quote_found("", SPEC) and not gates.quote_found("...", SPEC)


def test_spec_gate_downgrades():
    res = apply(f("preference"), f("requirement", "Python 3.8 에서도 동작해야 한다"),
                f("requirement", "목록은 생성 순서대로 출력한다"), f("requirement", "", sev="P1"),
                f("correctness"), f("security"), f("preference", sev="P3"))
    sev = [x["severity"] for x in res.data["findings"]]
    assert sev == ["P3", "P3", "P2", "P1", "P2", "P2", "P3"]
    assert res.downgraded["spec"] == 2
    notes = [x.get("note") for x in res.data["findings"]]
    assert notes[0] == "원래 P2: 취향" and notes[1] == "원래 P2: 인용한 요구를 과제·설계에서 찾지 못함"


def test_spec_gate_off_and_old_findings():
    res = apply(f("preference"), spec=None)
    assert res.data["findings"][0]["severity"] == "P2" and "spec" not in res.downgraded
    old = {"id": "", "severity": "P2", "new": True, "title": "t", "file": "a", "detail": "", "evidence": "a:1"}
    assert apply(old).data["findings"][0]["severity"] == "P2"                  # basis 없음 → correctness 취급
    assert apply(f("preference", evidence="")).downgraded == {"evidence": 1, "scope": 0}   # 근거 관문이 먼저


def test_schema_render_ledger_and_arbiter():
    it = REVIEW_SCHEMA["properties"]["findings"]["items"]
    assert set(it["required"]) == set(it["properties"]) and it["properties"]["basis"]["enum"][0] == "requirement"
    md = render_review({"status": "CHANGES_REQUESTED", "summary": "", "repro": [],
                        "findings": [f("requirement", "목록은 생성 순서대로 출력한다")]})
    assert "  요구: «목록은 생성 순서대로 출력한다»" in md

    class S:
        issues: list = []
    st = S()
    gates.update_ledger(st, "codex", 1, [{**f("requirement", "목록은 생성 순서대로"), "id": "I1"},
                                         {**f("correctness"), "id": "I2"}])
    assert st.issues[0]["basis"] == "requirement" and st.issues[0]["requirement"] == "목록은 생성 순서대로"
    text = format_issues(st.issues)
    assert "— 요구: «목록은 생성 순서대로»" in text and "— 근거 종류: 정확성" in text
    hint = output_instruction(True, True, "", gates=True, spec=True)
    assert "basis 가 preference 인 P1·P2 는 P3 로" in hint
    assert "basis 가 preference" not in output_instruction(True, True, "", gates=True, spec=False)


def scripted_reviewer(findings_round1):
    state = {"n": 0}

    def responder(req, n):
        if req.step == "review":
            state["n"] += 1
            fs = findings_round1 if state["n"] == 1 else []
            return json.dumps({"status": "CHANGES_REQUESTED" if fs else "APPROVED", "summary": "",
                               "findings": fs, "repro": []}, ensure_ascii=False)
        return MockAdapter(label="codex")._default_response(req)
    return responder


def test_build_spec_gate_end_to_end(tmp_path, monkeypatch):
    codex = MockAdapter(label="codex", responder=scripted_reviewer([f("preference")]))
    rc, seen, st, _ = run(tmp_path, monkeypatch, codex=codex)
    assert rc == 0 and len(st.review_history) == 1                        # 취향 P2 → P3, 1라운드 승인
    assert st.review_history[0]["downgraded"]["spec"] == 1
    review = [c for c in seen["codex"].calls if c.step == "review"][0]
    assert "basis 가 preference 인 P1·P2 는 P3 로" in review.prompt


def test_build_spec_gate_off(tmp_path, monkeypatch):
    codex = MockAdapter(label="codex", responder=scripted_reviewer([f("preference")]))
    rc, seen, st, _ = run(tmp_path, monkeypatch, codex=codex, toml="spec_gate = false\n")
    assert len(st.review_history) == 2 and "spec" not in st.review_history[0]["downgraded"]
    assert st.config["spec_gate"] is False
