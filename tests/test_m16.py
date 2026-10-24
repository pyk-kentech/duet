"""M16: 지적 원장과 판정 관문 (DESIGN.md 22장)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import tenure.orchestrator as orch_mod
from tenure import gates
from tenure.agents.mock import MockAdapter
from tenure.cli import main
from tenure.config import ConfigError, load_config
from tenure.state import RunState, list_run_dirs
from tenure.transcript import Transcript


def f(sev="P2", fid="", file="a.py", evidence="a.py:3 IndexError", title="t"):
    return {"id": fid, "severity": sev, "new": True, "title": title, "file": file, "detail": "d", "evidence": evidence}


def data(*fs, status="CHANGES_REQUESTED"):
    return {"status": status, "summary": "", "findings": list(fs), "repro": []}


# ====================================================================== 관문 단위
def test_evidence_gate():
    r = gates.apply_gates(data(f("P1", evidence=""), f("P2", evidence="  "), f("P2"), f("P3", evidence="")),
                          round_=1, open_ids=set(), changed_files=None, first_number=1)
    sev = [x["severity"] for x in r.data["findings"]]
    assert sev == ["P3", "P3", "P2", "P3"] and r.downgraded == {"evidence": 2, "scope": 0}
    assert r.data["findings"][0]["note"] == "원래 P1: 근거 없음"
    assert [x["id"] for x in r.data["findings"]] == ["I1", "I2", "I3", "I4"]


def test_scope_gate_round2_new_p2_only():
    changed = {"pkg/a.py", "README.md"}
    r = gates.apply_gates(data(f("P2", file="pkg/b.py"),               # 새·범위 밖 → P3
                               f("P2", file="./pkg/a.py:12"),          # 범위 안
                               f("P2", file="a.py"),                   # 경로 일부만 적어도 범위 안
                               f("P2", file=""),                       # 파일 모름 → P3
                               f("P1", file="other.py"),               # P1 은 그대로
                               f("P2", fid="I7", file="other.py")),    # 기존 지적은 그대로
                          round_=2, open_ids={"I7"}, changed_files=changed, first_number=8)
    got = [(x["id"], x["severity"]) for x in r.data["findings"]]
    assert got == [("I8", "P3"), ("I9", "P2"), ("I10", "P2"), ("I11", "P3"), ("I12", "P1"), ("I7", "P2")]
    assert r.downgraded == {"evidence": 0, "scope": 2}
    assert r.data["findings"][0]["note"] == "원래 P2: 이번 변경과 무관한 새 지적"
    assert r.data["findings"][5]["new"] is False and r.data["findings"][0]["new"] is True
    # 1라운드거나 기준을 모르면 범위 관문 없음
    r1 = gates.apply_gates(data(f("P2", file="pkg/b.py")), round_=1, open_ids=set(), changed_files=None, first_number=1)
    assert r1.data["findings"][0]["severity"] == "P2"


def test_unknown_id_becomes_new():
    r = gates.apply_gates(data(f(fid="I99")), round_=2, open_ids={"I1"}, changed_files={"a.py"}, first_number=2)
    assert r.data["findings"][0]["id"] == "I2"


class S:
    def __init__(self):
        self.issues = []


def test_ledger_update_and_resolve():
    st = S()
    gates.update_ledger(st, "codex", 1, [{**f(fid="I1"), "id": "I1"}, {**f(title="second"), "id": "I2"}])
    gates.update_ledger(st, "sec", 1, [{**f(), "id": "I3"}])
    assert [x["id"] for x in gates.open_issues(st, "codex")] == ["I1", "I2"]
    gates.update_ledger(st, "codex", 2, [{**f(sev="P1", title="renamed"), "id": "I2"}, {**f(), "id": "I4"}])
    by = {x["id"]: x for x in st.issues}
    assert by["I1"]["status"] == "resolved" and by["I1"]["closed_round"] == 2
    assert by["I2"]["status"] == "open" and by["I2"]["severity"] == "P1" and by["I2"]["title"] == "renamed"
    assert by["I3"]["status"] == "open"                       # 다른 리뷰어의 지적은 건드리지 않음
    assert gates.next_number(st) == 5
    assert gates.format_open(gates.open_issues(st, "codex")) == "- I2 [P1] renamed — `a.py`\n- I4 [P2] t — `a.py`"
    assert gates.format_open([]) == "(없음)"


# ====================================================================== 빌드 통합 (mock)
def run(tmp_path, monkeypatch, responder, *extra, toml=""):
    seen: dict = {}

    def factory(cfg, *, mock):
        seen["claude"] = MockAdapter(label="claude")
        seen["codex"] = MockAdapter(label="codex", responder=responder)
        return dict(seen)

    monkeypatch.setattr(orch_mod, "make_agents", factory)
    wd = tmp_path / "w"
    if toml:
        wd.mkdir()
        (wd / "tenure.toml").write_text(toml, encoding="utf-8")
    rc = main(["run", "t", "--workdir", str(wd), "--mock", "--debate-rounds", "0", "--max-review", "4", *extra])
    [rd] = list_run_dirs(wd)
    return rc, seen, RunState.load(rd), rd


def scripted(*rounds):
    """리뷰 라운드마다 줄 JSON. 다른 단계는 기본 mock 응답."""
    state = {"n": 0}

    def responder(req, n):
        if req.step != "review":
            return MockAdapter(label="codex")._default_response(req)
        state["n"] += 1
        return json.dumps(rounds[min(state["n"], len(rounds)) - 1], ensure_ascii=False)
    return responder


def reviews(seen):
    return [c for c in seen["codex"].calls if c.step == "review"]


def test_ledger_ids_carry_across_rounds(tmp_path, monkeypatch):
    rc, seen, st, rd = run(tmp_path, monkeypatch, scripted(
        data(f("P2", file="main.py", title="예외 처리 없음")),
        data(f("P2", fid="I1", file="main.py", title="예외 처리 아직 없음")),
        data(status="APPROVED")))
    assert rc == 0
    rv = reviews(seen)
    assert "(없음)" in rv[0].prompt.split("[열린 지적 목록")[1][:80]
    assert "- I1 [P2] 예외 처리 없음 — `main.py`" in rv[1].prompt
    assert "- I1 [P2] 예외 처리 아직 없음" in rv[2].prompt
    assert [(x["id"], x["status"], x["closed_round"]) for x in st.issues] == [("I1", "resolved", 3)]
    body = next(e for e in Transcript(rd).entries() if e.name.endswith("review2_codex.md")).body()
    assert "- [P2][I1] 예외 처리 아직 없음" in body
    assert st.review_history[1]["open_issues"] == 1 and st.review_history[2]["approved"]


def test_evidence_gate_unblocks(tmp_path, monkeypatch):
    rc, seen, st, rd = run(tmp_path, monkeypatch, scripted(data(f("P2", evidence="", title="막연한 걱정"))))
    assert rc == 0 and len(st.review_history) == 1
    h = st.review_history[0]
    assert h["approved"] and h["downgraded"] == {"evidence": 1, "scope": 0} and h["severity"]["P3"] == 1
    body = next(e for e in Transcript(rd).entries() if e.name.endswith("review1_codex.md")).body()
    assert "(원래 P2: 근거 없음)" in body and "## 고치면 좋은 것" in body


def test_scope_gate_unblocks_new_unrelated_finding(tmp_path, monkeypatch):
    # 1라운드: main.py 지적(막음) → 수정(main.py 만 바뀜) → 2라운드: 바뀌지 않은 other.py 에 새 P2 → P3 로 강등
    rc, seen, st, _ = run(tmp_path, monkeypatch, scripted(
        data(f("P2", file="main.py")),
        data(f("P2", file="other.py", title="새로 찾은 다른 문제"))))
    assert rc == 0 and len(st.review_history) == 2
    assert st.review_history[1]["approved"] and st.review_history[1]["downgraded"] == {"evidence": 0, "scope": 1}


def test_p1_never_scope_gated(tmp_path, monkeypatch):
    rc, _, st, _ = run(tmp_path, monkeypatch, scripted(
        data(f("P2", file="main.py")), data(f("P1", file="other.py")), data(status="APPROVED")))
    assert rc == 0 and not st.review_history[1]["approved"] and len(st.review_history) == 3


def test_gates_off(tmp_path, monkeypatch):
    rc, seen, st, _ = run(tmp_path, monkeypatch, scripted(data(f("P2", evidence="")), data(status="APPROVED")),
                          toml="review_gates = false\n")
    assert rc == 0 and not st.review_history[0]["approved"] and st.issues == []
    assert "downgraded" not in st.review_history[0]
    assert "evidence 가 비어 있으면 P3" not in reviews(seen)[0].prompt
    assert st.config["review_gates"] is False


def test_gate_hint_in_prompt(tmp_path, monkeypatch):
    _, seen, _, _ = run(tmp_path, monkeypatch, scripted(data(status="APPROVED")))
    p = reviews(seen)[0].prompt
    assert "evidence 가 비어 있으면 P3 로 낮추고" in p and "id 는 [열린 지적 목록]" in p


def test_config_validation():
    with pytest.raises(ConfigError):
        load_config(None, {"review_gates": "yes"}, global_defaults={})
    assert load_config(None, global_defaults={}).review_gates is True
