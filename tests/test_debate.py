from pathlib import Path

import pytest

from tenure.agents.mock import MockAdapter
from tenure.phases.common import AgentFailed, RateLimitStop
from tenure.phases.debate import DebatePhase, split_critique, split_revision
from tenure.state import FAILED, RUNNING, STOPPED_RATE_LIMIT, RunState
from tests.helpers import file_names, make_ctx


@pytest.mark.parametrize("rounds,expected", [
    (0, ["01_propose_claude.md", "02_propose_codex.md", "03_synthesize_codex.md"]),
    (1, ["01_propose_claude.md", "02_propose_codex.md",
         "03_r1_critique_claude.md", "04_r1_critique_codex.md", "05_synthesize_codex.md"]),
    (2, ["01_propose_claude.md", "02_propose_codex.md",
         "03_r1_critique_claude.md", "04_r1_critique_codex.md",
         "05_r2_critique_claude.md", "06_r2_critique_codex.md", "07_synthesize_codex.md"]),
])
def test_rounds_produce_files_in_order(tmp_path: Path, rounds, expected):
    ctx = make_ctx(tmp_path, overrides={"debate_rounds": rounds})
    final = DebatePhase(ctx).run()
    assert file_names(ctx.run_dir) == expected
    design = (tmp_path / "DESIGN.md").read_text(encoding="utf-8")
    assert design == final and "## 결정 사항" in design
    st = ctx.state
    assert st.proposals == {"claude": "01_propose_claude.md", "codex": "02_propose_codex.md"}
    assert len(st.critiques) == rounds * 2
    assert st.final_design == expected[-1]
    assert st.is_done("synthesize") and st.status == RUNNING
    assert len(st.calls) == len(expected)
    # run.json 저장됨
    assert RunState.load(ctx.run_dir).done == st.done


def test_synth_follows_config(tmp_path: Path):
    ctx = make_ctx(tmp_path, overrides={"debate_rounds": 0, "synth": "claude"})
    DebatePhase(ctx).run()
    assert file_names(ctx.run_dir)[-1] == "03_synthesize_claude.md"


def test_critique_prompts_use_previous_round_revisions(tmp_path: Path):
    seen: dict[str, list[str]] = {"claude": [], "codex": []}

    agents = {}
    for name in ("claude", "codex"):
        def make(name=name):
            def resp(req, n):
                seen[name].append(req.prompt)
                if req.step == "propose":
                    return f"{name}-P0"
                if req.step == "critique":
                    r = len([p for p in seen[name] if "[너의 현재 설계안]" in p])
                    return f"## 상대 안 비판\n{name}-C{r}\n\n## 개정안\n{name}-P{r}"
                return "## 결정 사항\nfinal"
            return resp
        agents[name] = MockAdapter(label=name, responder=make())
    ctx = make_ctx(tmp_path, agents=agents, overrides={"debate_rounds": 2})
    DebatePhase(ctx).run()

    # 라운드 1: 둘 다 상대의 P0 를 본다 / 라운드 2: 상대의 P1 을 본다
    c1, c2 = seen["claude"][1], seen["claude"][2]
    assert "[너의 현재 설계안]\nclaude-P0" in c1 and "codex-P0" in c1
    assert "[너의 현재 설계안]\nclaude-P1" in c2 and "codex-P1" in c2 and "codex-P0" not in c2
    # 종합 프롬프트에는 최종 개정안과 비판 요약이 들어간다
    synth_prompt = seen["codex"][-1]
    assert "claude-P2" in synth_prompt and "codex-P2" in synth_prompt
    assert "### R1 claude의 비판\nclaude-C1" in synth_prompt
    assert "### R2 codex의 비판\ncodex-C2" in synth_prompt
    assert "## 개정안" not in synth_prompt.split("[토론 중 나온 비판들]")[1]


def test_split_helpers():
    text = "## 상대 안 비판\n나쁨\n\n## 개정안\n# 새 안\n- 1"
    assert split_revision(text) == "# 새 안\n- 1"
    assert split_critique(text) == "나쁨"
    assert split_revision("헤더 없음") == "헤더 없음"
    assert split_critique("헤더 없음") == "헤더 없음"


def test_resume_skips_done_steps(tmp_path: Path):
    # 3번째 호출(claude 의 r1 비판)에서 두 번 연속 실패 → AgentFailed
    agents = {"claude": MockAdapter(label="claude", fail_on_calls={2, 3}), "codex": MockAdapter(label="codex")}
    ctx = make_ctx(tmp_path, agents=agents, overrides={"debate_rounds": 1})
    with pytest.raises(AgentFailed):
        DebatePhase(ctx).run()
    st = ctx.state
    assert st.status == FAILED and st.error
    assert st.is_done("propose:claude") and st.is_done("propose:codex")
    assert not st.is_done("critique:1:claude")
    assert file_names(ctx.run_dir) == ["01_propose_claude.md", "02_propose_codex.md",
                                       "03_r1_critique_claude_failed.md", "04_r1_critique_claude_failed.md"]
    assert not (tmp_path / "DESIGN.md").exists()

    # resume: 새 어댑터로 다시 실행하면 propose 는 다시 부르지 않는다
    st2 = RunState.load(ctx.run_dir)
    st2.status = RUNNING
    agents2 = {"claude": MockAdapter(label="claude"), "codex": MockAdapter(label="codex")}
    ctx2 = make_ctx(tmp_path, agents=agents2, overrides={"debate_rounds": 1}, state=st2)
    DebatePhase(ctx2).run()
    assert [c.step for c in agents2["claude"].calls] == ["critique"]
    assert [c.step for c in agents2["codex"].calls] == ["critique", "synthesize"]
    assert file_names(ctx2.run_dir)[-3:] == ["05_r1_critique_claude.md", "06_r1_critique_codex.md",
                                             "07_synthesize_codex.md"]
    assert (tmp_path / "DESIGN.md").exists()
    assert len(st2.calls) == 4 + 3


def test_retry_once_then_succeed(tmp_path: Path):
    agents = {"claude": MockAdapter(label="claude", fail_on_calls={1}), "codex": MockAdapter(label="codex")}
    ctx = make_ctx(tmp_path, agents=agents, overrides={"debate_rounds": 0})
    DebatePhase(ctx).run()
    names = file_names(ctx.run_dir)
    assert names[0] == "01_propose_claude_failed.md" and names[1] == "02_propose_claude.md"
    assert ctx.state.proposals["claude"] == "02_propose_claude.md"
    assert any("재시도" in m for m in ctx.logs)


def test_rate_limit_stops_immediately(tmp_path: Path):
    agents = {"claude": MockAdapter(label="claude"), "codex": MockAdapter(label="codex", rate_limit_on_calls={1})}
    ctx = make_ctx(tmp_path, agents=agents, overrides={"debate_rounds": 0})
    with pytest.raises(RateLimitStop) as e:
        DebatePhase(ctx).run()
    assert e.value.agent == "codex"
    assert ctx.state.status == STOPPED_RATE_LIMIT
    assert len(agents["codex"].calls) == 1  # 재시도 없음
    assert RunState.load(ctx.run_dir).status == STOPPED_RATE_LIMIT
