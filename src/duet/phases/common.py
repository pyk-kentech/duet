"""Phase 공통부: 에이전트 호출 + 기록 + 상태 갱신 + 실패 정책.

실패 정책(DESIGN 5.4):
- 한도 도달(rate_limited): 즉시 상태 저장 후 RateLimitStop.
- 비정상 종료/타임아웃: 1회 재시도. 또 실패하면 상태 저장 후 AgentFailed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

from duet.agents.base import AgentAdapter, AgentRequest, AgentResult, Mode
from duet.config import Config
from duet.runner import RunnerError
from duet.state import FAILED, STOPPED_RATE_LIMIT, RunState
from duet.transcript import Transcript

Logger = Callable[[str], None]


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
    ) -> CallOutcome:
        """에이전트를 호출하고 기록·상태를 갱신한다. 실패 정책을 적용한다."""
        agent = self.agents[agent_name]
        req = AgentRequest(prompt=prompt, cwd=self.workdir, mode=mode,
                           timeout_sec=self.cfg.timeout_sec, step=step, round=round_)
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

            meta = {
                "agent": agent_name, "adapter": agent.name, "step": step, "mode": mode.value,
                "round": round_, "attempt": attempt,
                "duration_sec": elapsed, "exit_code": result.exit_code,
                "rate_limited": result.rate_limited, "timed_out": result.timed_out,
                "ok": result.ok,
                **_usage_meta(result.usage),
                **(extra_meta or {}),
            }
            body = result.text if result.ok else _failure_body(result)
            path = self.transcript.save(label if result.ok else f"{label}_failed", body, meta)
            self.state.record_call(agent_name, step, elapsed, result.exit_code,
                                   rate_limited=result.rate_limited, timed_out=result.timed_out,
                                   file=path.name, usage=result.usage)

            if result.ok:
                self.log(f"{agent_name} ← {step} 완료 ({elapsed:.0f}초) → {path.name}")
                return CallOutcome(text=result.text, file=path.name, result=result)

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
