"""MockAdapter — 실제 CLI 없이 Phase/Orchestrator 흐름을 검증하기 위한 가짜 에이전트.

응답은 AgentRequest.step 으로 고른다(템플릿 문구에 의존하지 않음).
시나리오는 생성자 인자로 주입한다:
  - approve_on_review: 몇 번째 리뷰에서 승인할지 (0이면 끝까지 반려)
  - fail_on_calls / rate_limit_on_calls / timeout_on_calls: 몇 번째 호출(1부터)을 실패시킬지
  - responder: (req, call_no) -> str 를 주면 기본 응답을 완전히 대체
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import json

from duet.agents.base import AgentRequest, AgentResult, Mode, parse_structured

Responder = Callable[[AgentRequest, int], str]


@dataclass
class MockAdapter:
    label: str = "claude"                      # 흉내 내는 에이전트 이름
    approve_on_review: int = 2
    fail_on_calls: frozenset[int] = frozenset()
    rate_limit_on_calls: frozenset[int] = frozenset()
    timeout_on_calls: frozenset[int] = frozenset()
    responder: Responder | None = None
    write_file: str = "main.py"                # WRITE 모드에서 건드릴 파일
    delay_sec: float = 0.0
    calls: list[AgentRequest] = field(default_factory=list)
    reviews: int = 0
    sessions: int = 0                          # 새로 만든 세션 수 (이어가면 늘지 않음)

    def __post_init__(self) -> None:
        self.name = f"mock-{self.label}"
        self.fail_on_calls = frozenset(self.fail_on_calls)
        self.rate_limit_on_calls = frozenset(self.rate_limit_on_calls)
        self.timeout_on_calls = frozenset(self.timeout_on_calls)

    # ---------------------------------------------------------------- protocol
    def check(self) -> None:
        return None

    def ask(self, req: AgentRequest) -> AgentResult:
        self.calls.append(req)
        n = len(self.calls)
        if self.delay_sec:
            time.sleep(self.delay_sec)

        if n in self.timeout_on_calls:
            return self._result("", exit_code=-1, timed_out=True)
        if n in self.rate_limit_on_calls:
            return self._result("", exit_code=1, stderr="You've hit your usage limit.", rate_limited=True)
        if n in self.fail_on_calls:
            return self._result("", exit_code=1, stderr="mock failure")

        if req.resume_session:
            session_id = req.resume_session
        else:
            self.sessions += 1
            session_id = f"mock-{self.label}-s{self.sessions}"
        text = self.responder(req, n) if self.responder is not None else self._default_response(req)
        structured = parse_structured(text) if req.output_schema is not None else None
        return self._result(text, structured=structured, session_id=session_id, resumed=bool(req.resume_session))

    # ---------------------------------------------------------------- defaults
    def _default_response(self, req: AgentRequest) -> str:
        step = req.step
        if step == "propose":
            return f"# {self.name} 설계안\n- 모듈 2개\n"
        if step == "critique":
            return (
                f"## 상대 안 비판\n- ({self.name}) 과설계\n\n"
                f"## 개정안\n# {self.name} 개정안\n- 단일 파일\n"
            )
        if step == "synthesize":
            return f"## 결정 사항\n- ({self.name}) 단순한 쪽 채택\n\n# 최종 설계\n- {self.write_file} 하나\n"
        if step == "arbitrate":   # 기본: 열린 지적을 모두 유지(보수적, DESIGN.md 23장)
            import re

            ids = re.findall(r"^- (I\d+) ", req.prompt, re.MULTILINE)
            return json.dumps({"decisions": [{"id": i, "decision": "uphold", "reason": "요구사항에 해당"} for i in ids],
                               "summary": "지적이 타당하다"}, ensure_ascii=False)
        if step == "explore":
            return f"# {self.name} 사전 조사\n- 기존 코드 없음\n"
        if step == "audit":
            return ("## 반드시 고칠 것\n(없음)\n\n<verdict>\nstatus: APPROVED\n"
                    "must_fix: 0\np1: 0\np2: 0\np3: 0\n</verdict>\n")
        if step in ("implement", "fix"):
            if req.mode is Mode.WRITE:
                self._touch(req.cwd)
            return f"{self.name}: {step} 완료\n"
        if step == "review":
            self.reviews += 1
            approve = bool(self.approve_on_review and self.reviews >= self.approve_on_review)
            if req.output_schema is not None:   # JSON 판정 (DESIGN.md 21.2)
                findings = [] if approve else [{"id": "", "severity": "P2", "new": self.reviews == 1,
                                                "title": "예외 처리 없음", "file": self.write_file,
                                                "detail": "입력 오류를 처리하지 않는다",
                                                "evidence": f"{self.write_file}:1 입력 검사 없음",
                                                "basis": "correctness", "requirement": ""}]
                return json.dumps({"status": "APPROVED" if approve else "CHANGES_REQUESTED",
                                   "summary": f"{self.name} 리뷰", "findings": findings, "repro": []},
                                  ensure_ascii=False)
            if approve:
                return "## 반드시 고칠 것\n(없음)\n\n<verdict>\nstatus: APPROVED\nmust_fix: 0\n</verdict>\n"
            return (
                "## 반드시 고칠 것\n- 예외 처리 없음\n\n"
                "<verdict>\nstatus: CHANGES_REQUESTED\nmust_fix: 1\n</verdict>\n"
            )
        if req.mode is Mode.WRITE:
            self._touch(req.cwd)
        return "ok\n"

    def _touch(self, cwd: Path) -> None:
        p = Path(cwd) / self.write_file
        if p.exists():
            p.write_text(p.read_text(encoding="utf-8") + "# fix\n", encoding="utf-8")
        else:
            p.write_text("print('hi')\n", encoding="utf-8")

    def _result(
        self,
        text: str,
        *,
        exit_code: int = 0,
        stderr: str = "",
        rate_limited: bool = False,
        timed_out: bool = False,
        structured: dict | None = None,
        session_id: str | None = None,
        resumed: bool = False,
    ) -> AgentResult:
        return AgentResult(
            text=text,
            raw_stdout=text,
            raw_stderr=stderr,
            exit_code=exit_code,
            duration_sec=self.delay_sec,
            rate_limited=rate_limited,
            timed_out=timed_out,
            command=[self.name],
            structured=structured,
            session_id=session_id,
            resumed=resumed,
        )


def mock_pair(**kwargs: object) -> dict[str, MockAdapter]:
    """{"claude": MockAdapter, "codex": MockAdapter} 를 만든다. kwargs는 둘 다에 적용."""
    return {name: MockAdapter(label=name, **kwargs) for name in ("claude", "codex")}  # type: ignore[arg-type]


__all__: Iterable[str] = ("MockAdapter", "mock_pair", "Responder")
