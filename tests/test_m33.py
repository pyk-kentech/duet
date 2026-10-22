"""M33: 경쟁 초안 (DESIGN.md 36.15)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tenure.agents.mock import MockAdapter
from tenure.orchestrator import Orchestrator, OrchestratorError, RunOptions
from tenure.phases.race import RaceError, draft_path, judge, pick
from tenure.state import RunState
from tenure.ui.dashboard import ApiError, Dashboard, dispatch
from tenure.config import load_config
from tenure.workflow import WorkflowError, _parse_text, load_workflow
from tenure.workspace import Workspace

PASS_IF_OK = f'"{sys.executable}" -c "import os,sys; sys.exit(0 if os.path.exists(\'ok.txt\') else 1)"'


def repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    ws = Workspace(path)
    ws.git("init", "-q", "-b", "main")
    ws.git("config", "core.autocrlf", "false")
    (path / "README.md").write_text("# 프로젝트\n", encoding="utf-8")
    ws.git("add", "-A")
    ws.git("commit", "-q", "-m", "init")
    return path


def race_run(wd: Path, agents: dict | None = None, **overrides):
    factory = (lambda cfg, wf, mock=False: dict(agents)) if agents else None
    orch = Orchestrator(printer=lambda line: None, **({"role_factory": factory} if factory else {}))
    return orch.run(RunOptions(task="할일 CLI", workdir=wd, mock=True, register=False,
                               overrides={"workflow": "race", "worktree": "off", "test_command": "none",
                                          "report": False, **overrides}))


# ------------------------------------------------------------------ workflow
def test_race_workflow_and_rivals_validation():
    wf = load_workflow("race", None, load_config(None))
    b = wf.first("build")
    assert b.implementer == "claude" and b.rivals == ["codex"] and "race(" in b.describe()
    base = '[roles.a]\nagent = "claude"\n[roles.b]\nagent = "codex"\n[[steps]]\nkind = "build"\nimplementer = "a"\nreviewers = ["b"]\n'
    for bad, msg in (('rivals = ["a"]', "맞수"), ('rivals = ["zz"]', "정의되지 않은"), ('rivals = ["a", "b"]', "1~1")):
        with pytest.raises(WorkflowError, match=msg):
            _parse_text(base + bad + "\n", name_hint="t", source="test", where="t")


# ------------------------------------------------------------------ judge
def s(tests=None, approved=False, blocking=1, lines=10):
    return {"tests": tests, "approved": approved, "blocking": blocking, "lines": lines}


@pytest.mark.parametrize("a,b,win,why", [
    (s(tests="failed"), s(tests="passed"), "b", "테스트"),
    (s(tests=None), s(tests="failed"), "a", "테스트"),
    (s(approved=False, blocking=0), s(approved=True, blocking=0), "b", "승인"),
    (s(blocking=3), s(blocking=1), "b", "막는 지적 1개 대 3개"),
    (s(lines=50), s(lines=20), "b", "바뀐 줄 20 대 50"),
    (s(), s(), "a", "구현 담당"),
])
def test_judge_order(a, b, win, why):
    w, reason = judge({"a": a, "b": b}, ["a", "b"])
    assert w == win and why in reason


# ------------------------------------------------------------------ run
def test_race_run_tie_goes_to_lead_then_continues(tmp_path):
    wd = repo(tmp_path / "p")
    out = race_run(wd)
    st, rd = out.state, out.run_dir
    race = st.race
    assert race["winner"] == "claude" and race["loser"] == "codex" and "구현 담당" in race["reason"]
    assert set(race["drafts"]) == {"claude", "codex"}
    assert race["drafts"]["codex"]["reviewer"] == "claude" and race["drafts"]["claude"]["reviewer"] == "codex"
    # 승자 초안의 1라운드가 이 실행의 1라운드, 2라운드는 승자 구현·패자 리뷰
    assert st.review_history[0]["draft"] == "claude" and st.review_history[0]["file"].startswith("drafts/claude/")
    assert st.status == "done_approved" and len(st.review_history) == 2
    names = sorted(p.name for p in rd.glob("*.md"))
    assert any("impl2_claude" in n for n in names) and any("review2_codex" in n for n in names)
    # 초안 비용도 이 실행 사용량에 합침: 초안 구현 2 + 리뷰 2 + 고치기 1 + 리뷰 1
    assert len(st.calls) == 6 and sum(1 for c in st.calls if (c.file or "").startswith("drafts/")) == 4
    ws = Workspace(wd)
    for r in ("claude", "codex"):
        assert ws.git("rev-parse", "--verify", "--quiet", f"refs/heads/tenure/{st.run_id}-{r}").strip()
        assert not draft_path(wd, st.run_id, r).exists()          # 초안 worktree 는 지움
        assert (rd / "drafts" / r / "run.json").is_file()
    assert ws.git("merge-base", "--is-ancestor", race["drafts"]["claude"]["head"], "HEAD", check=False) == ""


def test_race_tests_decide_winner(tmp_path):
    wd = repo(tmp_path / "p")
    agents = {"claude": MockAdapter(label="claude", write_file="main.py"),
              "codex": MockAdapter(label="codex", write_file="ok.txt", approve_on_review=1)}
    out = race_run(wd, agents, test_command=PASS_IF_OK)
    race = out.state.race
    assert race["drafts"]["codex"]["tests"] == "passed" and race["drafts"]["claude"]["tests"] == "failed"
    assert race["winner"] == "codex" and "테스트" in race["reason"]
    assert (wd / "ok.txt").exists() and not (wd / "main.py").exists()
    # 2라운드: codex 가 고치고 claude 가 리뷰
    fix_calls = [c for c in agents["codex"].calls if c.step == "fix"]
    claude_reviews = [c for c in agents["claude"].calls if c.step == "review"]
    assert len(fix_calls) == 1 and len(claude_reviews) == 2


def test_race_round1_approved_finishes(tmp_path):
    wd = repo(tmp_path / "p")
    agents = {"claude": MockAdapter(label="claude", approve_on_review=1),
              "codex": MockAdapter(label="codex", approve_on_review=1)}
    out = race_run(wd, agents)
    assert out.state.status == "done_approved" and len(out.state.review_history) == 1
    assert out.state.race["drafts"]["claude"]["approved"] and out.state.race["winner"] == "claude"


def test_pick_other_draft(tmp_path):
    wd = repo(tmp_path / "p")
    agents = {"claude": MockAdapter(label="claude", write_file="main.py"),
              "codex": MockAdapter(label="codex", write_file="other.py")}
    out = race_run(wd, agents)
    rd, rid = out.run_dir, out.state.run_id
    prev = Workspace(wd).head(short=False)
    with pytest.raises(RaceError, match="초안이 없습니다"):
        pick(wd, rd, "nobody")
    res = pick(wd, rd, "codex")
    assert res["kept"] == f"tenure/{rid}-prev-1" and (wd / "other.py").exists() and not (wd / "main.py").exists()
    assert Workspace(wd).git("rev-parse", res["kept"]).strip() == prev
    st = RunState.load(rd)
    assert st.race["picked"] == "codex" and st.stop_reason == "picked" and st.status == "done_unapproved"
    with pytest.raises(OrchestratorError, match="바꾼 실행은 이어할 수 없습니다"):
        Orchestrator(printer=lambda line: None).resume(wd, rid, max_review=5)
    (wd / "dirty.txt").write_text("x", encoding="utf-8")
    with pytest.raises(RaceError, match="커밋 안 한"):
        pick(wd, rd, "claude")


# ------------------------------------------------------------------ dashboard
def test_dashboard_drafts(tmp_path):
    wd = repo(tmp_path / "p")
    agents = {"claude": MockAdapter(label="claude", write_file="main.py"),
              "codex": MockAdapter(label="codex", write_file="other.py")}
    out = race_run(wd, agents)
    rid = out.state.run_id
    d = Dashboard()
    d.registry.add(wd)
    detail = d.run(str(wd), rid)
    drafts = [e for e in detail["entries"] if e.get("draft")]
    assert {e["draft"] for e in drafts} == {"claude", "codex"} and all(e["name"].startswith("drafts/") for e in drafts)
    stamps = [e["meta"].get("timestamp") for e in detail["entries"]]
    assert stamps == sorted(stamps)
    body = d.entry(str(wd), rid, drafts[0]["name"])
    assert body["name"] == drafts[0]["name"] and body["body"]
    with pytest.raises(ApiError):
        d.entry(str(wd), rid, "drafts/../run.json")
    assert "other.py" in d.diff(str(wd), rid, draft="codex")["text"]
    assert "main.py" in d.diff(str(wd), rid, draft="claude")["text"]
    with pytest.raises(ApiError):
        d.diff(str(wd), rid, draft="nobody")
    res = dispatch(d, "pick", {"project": str(wd), "run": rid, "draft": "codex"})
    assert res["role"] == "codex" and (wd / "other.py").exists()
