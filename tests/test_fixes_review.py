"""독립 리뷰에서 나온 버그들의 회귀 테스트."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from duet.agents.base import AgentRequest, Mode
from duet.agents.claude_code import ClaudeCodeAdapter
from duet.agents.codex import CodexAdapter
from duet.agents.mock import MockAdapter
from duet.cli import main
from duet.config import Config, load_config
from duet.phases.build import BuildPhase, build_review_diff
from duet.phases.debate import DebatePhase, is_success
from duet.runner import run_process
from duet.state import DONE_APPROVED, FAILED, RUNNING, RunState, list_run_dirs
from duet.transcript import Transcript
from duet.verdict import Status, parse_verdict
from duet.workspace import Workspace
from tests.conftest import read_dump
from tests.helpers import file_names, make_ctx
import duet.orchestrator as orch_mod


# ---------------------------------------------------------------- 1. 긴 한글 프롬프트 (E2BIG)
@pytest.mark.parametrize("adapter_cls", [ClaudeCodeAdapter, CodexAdapter])
def test_long_korean_prompt_goes_to_stdin(adapter_cls, fake_cfg: Config, tmp_path: Path, dump_path, monkeypatch):
    monkeypatch.setenv("DUET_FAKE_DUMP", str(dump_path))
    prompt = "가" * 60_000            # 6만 자 = 18만 바이트 > Linux 인자 한도 128KiB
    assert len(prompt) < fake_cfg.prompt_arg_max_bytes   # 글자 수로만 재면 인자로 넘길 뻔함
    r = adapter_cls(fake_cfg).ask(AgentRequest(prompt, tmp_path, Mode.READ, 20, "critique"))
    assert r.ok, r.raw_stderr
    assert read_dump(dump_path)["stdin"] == prompt


def test_old_config_key_still_accepted(tmp_path: Path):
    (tmp_path / "duet.toml").write_text("prompt_arg_max_chars = 5000\n", encoding="utf-8")
    assert load_config(tmp_path).prompt_arg_max_bytes == 5000


def test_exec_error_becomes_failed_state(tmp_path: Path):
    class Boom(MockAdapter):
        def ask(self, req):
            raise OSError(7, "Argument list too long")

    ctx = make_ctx(tmp_path, agents={"claude": Boom(label="claude"), "codex": MockAdapter(label="codex")},
                   overrides={"debate_rounds": 0})
    from duet.phases.common import AgentFailed
    with pytest.raises(AgentFailed, match="실행 불가"):
        DebatePhase(ctx).run()
    assert RunState.load(ctx.run_dir).status == FAILED


# ---------------------------------------------------------------- 2. git 오류
def test_nested_repo_by_implementer_fails_cleanly_and_resume_does_not_repay(tmp_path: Path, monkeypatch, capsys):
    wd = tmp_path / "x"

    def make_nested(req, n):
        sub = req.cwd / "app"
        sub.mkdir(exist_ok=True)
        subprocess.run(["git", "init", "-q", str(sub)], check=True)
        (sub / "a.txt").write_text("x", encoding="utf-8")
        return "구현 완료"

    first = {"claude": MockAdapter(label="claude", responder=make_nested), "codex": MockAdapter(label="codex")}
    second = {"claude": MockAdapter(label="claude"), "codex": MockAdapter(label="codex", approve_on_review=1)}
    it = iter([first, second])
    monkeypatch.setattr(orch_mod, "make_agents", lambda cfg, *, mock: next(it))
    (tmp_path / "x").mkdir()
    (wd / "DESIGN.md").write_text("# d\n", encoding="utf-8")
    assert main(["run", "t", "--workdir", str(wd), "--mock", "--skip-design", "--max-review", "1"]) == 3
    out = capsys.readouterr().out
    assert "git 오류" in out
    st = RunState.load(list_run_dirs(wd)[-1])
    assert st.status == FAILED and st.error.startswith("git 오류")
    assert st.is_done("impl:1:called") and not st.is_done("impl:1")

    # 사용자가 하위 저장소를 정리한 뒤 resume → 구현을 다시 부르지 않고 커밋부터
    import shutil
    shutil.rmtree(wd / "app" / ".git")
    assert main(["resume", "--workdir", str(wd)]) == 0
    assert second["claude"].calls == []
    assert [c.step for c in second["codex"].calls] == ["review"]
    assert RunState.load(list_run_dirs(wd)[-1]).status == DONE_APPROVED


def test_global_gpgsign_does_not_break_commits(tmp_path: Path, monkeypatch):
    gitcfg = tmp_path / "gitconfig"
    gitcfg.write_text("[commit]\n\tgpgsign = true\n[gpg]\n\tprogram = false\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitcfg))
    wd = tmp_path / "x"
    assert main(["run", "t", "--workdir", str(wd), "--mock", "--debate-rounds", "0"]) == 0
    assert Workspace(wd).commit_count() == 3


# ---------------------------------------------------------------- 3. resume 시 사용자 수정 보존
def test_resume_in_review_keeps_user_edits(tmp_path: Path, monkeypatch, capsys):
    wd = tmp_path / "x"
    first = {"claude": MockAdapter(label="claude"), "codex": MockAdapter(label="codex", fail_on_calls={3, 4})}
    second = {"claude": MockAdapter(label="claude"), "codex": MockAdapter(label="codex", approve_on_review=1)}
    it = iter([first, second])
    monkeypatch.setattr(orch_mod, "make_agents", lambda cfg, *, mock: next(it))
    assert main(["run", "t", "--workdir", str(wd), "--mock", "--debate-rounds", "0"]) == 3
    (wd / "notes_by_user.txt").write_text("내 메모", encoding="utf-8")
    (wd / "DESIGN.md").write_text("# 사람이 고친 설계\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["resume", "--workdir", str(wd)]) == 0
    out = capsys.readouterr().out
    assert (wd / "notes_by_user.txt").read_text(encoding="utf-8") == "내 메모"
    assert (wd / "DESIGN.md").read_text(encoding="utf-8") == "# 사람이 고친 설계\n"
    assert "보존 커밋" in out and "리뷰어가 파일을 변경함" not in out
    assert not Workspace(wd).dirty()
    # 리뷰어는 사용자가 추가한 파일도 diff 에서 봤다
    assert "notes_by_user.txt" in second["codex"].calls[0].prompt


# ---------------------------------------------------------------- 4. 실패 기록을 개정안으로 읽지 않기
def test_debate_uses_successful_retry_not_failed_record(tmp_path: Path):
    ctx = make_ctx(tmp_path, overrides={"debate_rounds": 1})
    tr: Transcript = ctx.transcript
    tr.save("propose_claude", "claude-P0", {"agent": "claude", "step": "propose", "round": 0, "exit_code": 0, "ok": True})
    tr.save("propose_codex", "codex-P0", {"agent": "codex", "step": "propose", "round": 0, "exit_code": 0, "ok": True})
    ctx.state.proposals = {"claude": "01_propose_claude.md", "codex": "02_propose_codex.md"}
    for k in ("propose:claude", "propose:codex"):
        ctx.state.mark_done(k)
    # exit 0 이지만 한도로 실패한 기록 → 그 뒤 성공한 재시도
    tr.save("r1_critique_claude_failed", "# 호출 실패: 구독 한도 도달\n## 개정안\n쓰레기",
            {"agent": "claude", "step": "critique", "round": 1, "exit_code": 0, "rate_limited": True, "ok": False})
    tr.save("r1_critique_claude", "## 상대 안 비판\n진짜비판\n\n## 개정안\nclaude-P1",
            {"agent": "claude", "step": "critique", "round": 1, "exit_code": 0, "ok": True})
    ctx.state.mark_done("critique:1:claude")
    seen = []
    ctx.agents["codex"] = MockAdapter(label="codex", responder=lambda req, n: (seen.append(req.prompt) or
                                      ("## 상대 안 비판\nc\n\n## 개정안\ncodex-P1" if req.step == "critique" else "## 결정 사항\nok")))
    DebatePhase(ctx).run()
    synth = seen[-1]
    assert "claude-P1" in synth and "쓰레기" not in synth and "호출 실패" not in synth
    assert "### R1 claude의 비판\n진짜비판" in synth


def test_is_success_legacy_meta(tmp_path: Path):
    tr = Transcript(tmp_path)
    tr.save("a", "x", {"exit_code": 0, "rate_limited": True})
    tr.save("b", "x", {"exit_code": 0})
    tr.save("c_failed", "x", {"exit_code": 0})
    a, b, c = tr.entries()
    assert not is_success(a) and is_success(b) and not is_success(c)


# ---------------------------------------------------------------- 5. 백그라운드 프로세스가 파이프를 잡아도
def test_finished_call_not_reported_as_timeout_when_background_holds_pipe(tmp_path: Path):
    r = run_process(["bash", "-c", "sleep 30 & echo '{\"result\": \"ok\"}'; exit 0"], cwd=tmp_path, timeout_sec=15)
    assert not r.timed_out and r.exit_code == 0
    assert '"ok"' in r.stdout
    assert r.duration_sec < 10


def test_large_stdin_and_output(tmp_path: Path):
    data = "한" * 300_000
    r = run_process([sys.executable, "-c", "import sys; d=sys.stdin.read(); print(len(d)); sys.stderr.write('e'*200000)"],
                    cwd=tmp_path, stdin_text=data, timeout_sec=30)
    assert r.ok and r.stdout.strip() == "300000" and len(r.stderr) == 200_000


# ---------------------------------------------------------------- 6. 판정 마크다운
@pytest.mark.parametrize("text,status", [
    ("<verdict>\n**status:** APPROVED\n**must_fix:** 0\n</verdict>", Status.APPROVED),
    ("<verdict>\nstatus: **APPROVED**\nmust_fix: `0`\n</verdict>", Status.APPROVED),
    ("<verdict>\n- status: APPROVED\n- must_fix: 0\n</verdict>", Status.APPROVED),
    ("<verdict>\n* **status**: CHANGES_REQUESTED\n* must_fix: 2\n</verdict>", Status.CHANGES_REQUESTED),
    ("**VERDICT:** `APPROVED`", Status.APPROVED),
])
def test_verdict_markdown_variants(text, status):
    v = parse_verdict(text)
    assert v.status is status and not v.parse_failed


def test_verdict_markdown_contradiction_still_caught():
    v = parse_verdict("<verdict>\n**status:** APPROVED\n- must_fix: 1\n</verdict>")
    assert v.status is Status.CHANGES_REQUESTED and v.contradiction


# ---------------------------------------------------------------- 7. 잠금 파일이 diff 를 밀어내지 않기
def test_review_diff_excludes_lockfiles_and_keeps_file_summary(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.ensure_repo()
    base = ws.commit_all("base")
    (tmp_path / "package-lock.json").write_text("{\n" + '  "x": 1,\n' * 20000 + "}\n", encoding="utf-8")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "yarn.lock").write_text("lock\n" * 1000, encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('핵심 코드')\n", encoding="utf-8")
    (tmp_path / "DESIGN.md").write_text("# d\n", encoding="utf-8")
    ws.commit_all("impl")
    cfg = load_config(None)
    d = build_review_diff(ws, base, cfg.diff_excludes, 5000)
    assert d.startswith("[변경 파일 요약]")
    summary, body = d.split("\n\n", 1)
    assert "package-lock.json" in summary and "src/main.py" in summary and "web/yarn.lock" in summary
    assert "DESIGN.md" not in summary
    assert "핵심 코드" in body and '"x": 1' not in body and "lock\nlock" not in body


def test_build_prompt_uses_new_diff(tmp_path: Path):
    seen = []

    def rev(req, n):
        seen.append(req.prompt)
        return "<verdict>\nstatus: APPROVED\nmust_fix: 0\n</verdict>"

    ctx = make_ctx(tmp_path, agents={"claude": MockAdapter(label="claude"),
                                     "codex": MockAdapter(label="codex", responder=rev)})
    (tmp_path / "DESIGN.md").write_text("# d\n", encoding="utf-8")
    assert BuildPhase(ctx).run()
    assert "[변경 파일 요약]" in seen[0] and "main.py" in seen[0]


# ---------------------------------------------------------------- 8. codex '-' 로 시작하는 프롬프트
def test_codex_prompt_starting_with_dash(fake_cfg: Config, tmp_path: Path, dump_path, monkeypatch):
    monkeypatch.setenv("DUET_FAKE_DUMP", str(dump_path))
    r = CodexAdapter(fake_cfg).ask(AgentRequest("- 목록으로 시작하는 프롬프트", tmp_path, Mode.READ, 20, "review"))
    assert r.ok
    assert read_dump(dump_path)["argv"][-2:] == ["--", "- 목록으로 시작하는 프롬프트"]
