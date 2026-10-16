"""Phase 공통부: 에이전트 호출 + 기록 + 상태 갱신 + 실패 정책.

실패 정책(DESIGN 5.4):
- 한도 도달(rate_limited): 즉시 상태 저장 후 RateLimitStop.
- 비정상 종료/타임아웃: 1회 재시도. 또 실패하면 상태 저장 후 AgentFailed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Mapping

from duet.agents.base import AgentAdapter, AgentRequest, AgentResult, Mode
from duet.config import Config
from duet.prompts import render
from duet.runner import RunnerError
from duet.state import FAILED, STOPPED_RATE_LIMIT, RunState
from duet.transcript import Transcript

if TYPE_CHECKING:
    from duet.workflow import Workflow

Logger = Callable[[str], None]
EXPLORE_NOTE_MAX = 20_000   # 사전 조사 결과를 프롬프트에 붙일 때 최대 길이
DESIGN_DOC_DEFAULT = "DESIGN.md"


class PhaseStop(Exception):
    """Phase를 중단해야 하는 상황. status는 이미 상태에 기록됨."""

    def __init__(self, message: str, status: str):
        super().__init__(message)
        self.status = status


class RateLimitStop(PhaseStop):
    def __init__(self, agent: str, step: str):
        super().__init__(f"{agent}의 구독 한도에 도달했습니다 ({step}).", STOPPED_RATE_LIMIT)
        self.agent = agent


class AgentFailed(PhaseStop):
    def __init__(self, agent: str, step: str, reason: str):
        super().__init__(f"{agent} 호출이 반복 실패했습니다 ({step}): {reason}", FAILED)
        self.agent = agent


@dataclass
class CallOutcome:
    text: str
    file: str            # transcript 파일 이름
    result: AgentResult


@dataclass
class PhaseContext:
    task: str
    workdir: Path
    cfg: Config
    agents: Mapping[str, AgentAdapter]
    state: RunState
    transcript: Transcript
    run_dir: Path
    log: Logger = field(default=lambda msg: None)
    retries: int = 1
    # 워크플로 템플릿 (DESIGN.md 19장). None 이면 agents 의 키가 곧 CLI 이름(classic)
    workflow: "Workflow | None" = None

    # ---------------------------------------------------------------- roles
    def cli_of(self, role: str) -> str:
        """역할 → CLI 이름(claude/codex). 기록·사용량 합계는 CLI 기준."""
        if self.workflow is not None and role in self.workflow.roles:
            return self.workflow.roles[role].agent
        return role

    @property
    def design_doc(self) -> str:
        """설계 문서 경로(작업 폴더 기준). 변경 설계면 docs/changes/<run>.md (DESIGN.md 19.5)."""
        return self.state.design_doc or DESIGN_DOC_DEFAULT

    @property
    def change_mode(self) -> bool:
        return bool(self.state.design_doc) and self.state.design_doc != DESIGN_DOC_DEFAULT

    def design_note(self) -> str:
        if not self.change_mode:
            return ""
        return (f"이번 작업은 기존 프로젝트를 바꾸는 것이다. 이번 변경의 설계는 {self.design_doc} 에 있다. "
                "프로젝트 전체 설계(DESIGN.md, 있다면)와 기존 코드의 관례를 함께 따르고, "
                "과제에 필요하지 않은 기존 동작은 바꾸지 마라.")

    def agent_config(self, role: str):
        """역할이 쓰는 CLI 설정(모델·강도 포함)."""
        if self.workflow is not None and role in self.workflow.roles:
            return self.workflow.roles[role].agent_config(self.cfg)
        return self.cfg.agent(self.cli_of(role))

    def can_run_commands(self, role: str) -> bool:
        """읽기 모드에서 이 역할이 명령을 실행할 수 있는가 (DESIGN.md 19.6).

        Claude 는 read_args 에 Bash 가 있을 때만(기본 Read,Glob,Grep 이라 불가), Codex read-only 샌드박스는 가능.
        """
        cli = self.cli_of(role)
        if cli != "claude":
            return True
        if self.workflow is not None and role in self.workflow.roles:
            ac = self.workflow.roles[role].agent_config(self.cfg)
        else:
            ac = self.cfg.agent(cli)
        return any("Bash" in a for a in ac.read_args)

    def prompt(self, role: str, step: str, **values: object) -> str:
        """step 의 프롬프트. 역할이 템플릿을 바꿨으면 그것을 쓰고, 사전 조사·변경 설계 안내·역할 지시를 붙인다."""
        r = self.workflow.roles.get(role) if self.workflow is not None else None
        name = r.templates.get(step, step) if r is not None else step
        values.setdefault("design_doc", self.design_doc)
        values.setdefault("design_note", self.design_note())
        text = render(name, self.workdir, **values)
        if self.change_mode and step in ("propose", "critique", "synthesize"):
            text += ("\n\n## 기존 프로젝트의 변경\n\n이 과제는 기존 프로젝트를 바꾸는 작업이다. 프로젝트 전체를 다시 "
                     "설계하지 말고 이번 변경만 설계해라: 바꿀 파일·함수, 지켜야 할 기존 동작, 테스트, 문서 갱신. "
                     f"결과는 {self.design_doc} 에 저장되고 DESIGN.md 는 덮어쓰지 않는다.")
        if step in ("propose", "implement"):
            notes = self._explore_notes()
            if notes:
                text += "\n\n## 사전 조사 (duet 가 먼저 기존 코드를 조사한 결과)\n\n" + notes
        if r is not None and r.instructions.strip():
            text += "\n\n## 이 역할에 대한 추가 지시\n\n" + r.instructions.strip()
        return text

    def _explore_notes(self) -> str:
        parts = []
        for sid, file in self.state.explores.items():
            try:
                body = self.transcript.read(file).strip()
            except OSError:
                continue
            if len(body) > EXPLORE_NOTE_MAX:
                body = body[:EXPLORE_NOTE_MAX] + "\n... (길어서 잘림)"
            parts.append(f"### {sid}\n{body}" if len(self.state.explores) > 1 else body)
        return "\n\n".join(parts)

    # ---------------------------------------------------------------- state
    def save(self) -> None:
        self.state.save(self.run_dir)

    def set_position(self, phase: str, step: str, round_: int) -> None:
        self.state.phase, self.state.step, self.state.round = phase, step, round_

    # ---------------------------------------------------------------- call
    def call(
        self,
        agent_name: str,
        step: str,
        prompt: str,
        mode: Mode,
        *,
        label: str,
        round_: int = 0,
        extra_meta: Mapping[str, object] | None = None,
        output_schema: dict | None = None,
        resume_session: str | None = None,
        fallback_prompt: str | None = None,
        transform: Callable[[AgentResult], str] | None = None,
        effort: str | None = None,
    ) -> CallOutcome:
        """에이전트를 호출하고 기록·상태를 갱신한다. 실패 정책을 적용한다.

        transform: 성공한 결과를 기록·반환할 본문으로 바꾼다(예: JSON 판정 → 마크다운 리뷰, DESIGN.md 21.2).
        """
        agent = self.agents[agent_name]
        req = AgentRequest(prompt=prompt, cwd=self.workdir, mode=mode,
                           timeout_sec=self.cfg.timeout_sec, step=step, round=round_,
                           output_schema=output_schema, resume_session=resume_session,
                           fallback_prompt=fallback_prompt, effort=effort)
        attempt = 0
        while True:
            attempt += 1
            started = time.monotonic()
            self.log(f"{agent_name} ← {step}" + (f" (재시도 {attempt - 1})" if attempt > 1 else "") + " 실행 중...")
            try:
                result = agent.ask(req)
            except (OSError, RunnerError) as e:
                # 실행 자체가 안 됨(인자 길이 초과, 실행 파일 사라짐 등). 재시도해도 같으므로 바로 멈춘다.
                self.state.status = FAILED
                self.state.error = f"{agent_name} {step} 실행 불가: {e}"
                self.save()
                raise AgentFailed(agent_name, step, f"실행 불가: {e}") from e
            elapsed = result.duration_sec or (time.monotonic() - started)

            cli = self.cli_of(agent_name)
            meta = {
                "agent": cli, **({"role": agent_name} if cli != agent_name else {}),
                "adapter": agent.name, "step": step, "mode": mode.value,
                "round": round_, "attempt": attempt,
                "duration_sec": elapsed, "exit_code": result.exit_code,
                "rate_limited": result.rate_limited, "timed_out": result.timed_out,
                "ok": result.ok,
                **_usage_meta(result.usage),
                **({"resumed": True} if result.resumed else {}),
                **({"session_id": result.session_id} if result.session_id else {}),
                **({"structured": True} if result.structured is not None else {}),
                **(extra_meta or {}),
            }
            text = (transform(result) if transform is not None else result.text) if result.ok else result.text
            body = text if result.ok else _failure_body(result)
            path = self.transcript.save(label if result.ok else f"{label}_failed", body, meta)
            self.state.record_call(cli, step, elapsed, result.exit_code,
                                   rate_limited=result.rate_limited, timed_out=result.timed_out,
                                   file=path.name, usage=result.usage,
                                   role=agent_name if cli != agent_name else None)

            if result.ok:
                self.log(f"{agent_name} ← {step} 완료 ({elapsed:.0f}초)"
                         + (" [세션 이어감]" if result.resumed else "") + f" → {path.name}")
                return CallOutcome(text=text, file=path.name, result=result)

            reason = result.failure_reason()
            self.log(f"{agent_name} ← {step} 실패: {reason} → {path.name}")
            if result.rate_limited:
                self.state.status = STOPPED_RATE_LIMIT
                self.state.error = f"{agent_name} 한도 도달 ({step})"
                self.save()
                raise RateLimitStop(agent_name, step)
            if attempt > self.retries:
                self.state.status = FAILED
                self.state.error = f"{agent_name} {step} 실패: {reason}"
                self.save()
                raise AgentFailed(agent_name, step, reason)


def _failure_body(result: AgentResult) -> str:
    parts = [f"# 호출 실패: {result.failure_reason()}", ""]
    if result.text:
        parts += ["## 응답 본문", result.text, ""]
    if result.raw_stderr.strip():
        parts += ["## stderr (마지막 4000자)", "```", result.raw_stderr[-4000:], "```", ""]
    if result.raw_stdout.strip() and result.raw_stdout.strip() != result.text.strip():
        parts += ["## stdout (마지막 4000자)", "```", result.raw_stdout[-4000:], "```", ""]
    return "\n".join(parts)


def _usage_meta(u: dict | None) -> dict[str, object]:
    if not u:
        return {}
    meta: dict[str, object] = {}
    for src, dst in (("model", "model"), ("effort", "effort"), ("input_tokens", "tokens_in"),
                     ("output_tokens", "tokens_out"), ("cost_usd", "cost_usd")):
        if u.get(src) not in (None, ""):
            meta[dst] = u[src]
    return meta
