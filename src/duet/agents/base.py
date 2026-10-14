"""에이전트 어댑터 공통 인터페이스.

어댑터는 얇게 유지한다: 명령어 조립 → 실행(duet.runner) → 결과 파싱.
판단 로직(재시도, 판정, 흐름)은 Phase/Orchestrator가 맡는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Protocol, runtime_checkable


class Mode(Enum):
    READ = "read"    # 파일 읽기만 허용 (설계, 리뷰)
    WRITE = "write"  # 파일 수정 + 셸 실행 허용 (구현, 수정)


@dataclass
class AgentRequest:
    prompt: str
    cwd: Path
    mode: Mode
    timeout_sec: int
    # 어떤 단계의 호출인지("propose", "critique", "synthesize", "implement", "fix", "review").
    # 로그/기록용이며 MockAdapter가 응답을 고를 때도 쓴다.
    step: str = ""


@dataclass
class AgentResult:
    text: str                 # 최종 응답 본문
    raw_stdout: str
    raw_stderr: str
    exit_code: int
    duration_sec: float
    rate_limited: bool = False  # 구독 한도 걸림 감지 여부
    timed_out: bool = False
    command: list[str] = field(default_factory=list, repr=False)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.rate_limited

    def failure_reason(self) -> str:
        """사람에게 보여줄 실패 사유(성공이면 빈 문자열)."""
        if self.timed_out:
            return "시간 초과"
        if self.rate_limited:
            return "구독 한도 도달"
        if self.exit_code != 0:
            return f"비정상 종료 (exit {self.exit_code})"
        return ""


class AgentError(Exception):
    """에이전트 관련 예외."""


class AgentNotAvailable(AgentError):
    """설치/로그인 확인 실패. 메시지는 사용자에게 그대로 보여준다."""


@runtime_checkable
class AgentAdapter(Protocol):
    name: str  # "claude" | "codex" | "mock-claude" ...

    def check(self) -> None:
        """설치/로그인 확인. 실패 시 AgentNotAvailable."""
        ...

    def ask(self, req: AgentRequest) -> AgentResult: ...


def compile_rate_limit_patterns(patterns: Iterable[str]) -> list[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def detect_rate_limit(texts: Iterable[str], patterns: Iterable[re.Pattern[str]]) -> bool:
    """출력 텍스트들에서 한도 도달 문구가 보이면 True."""
    for text in texts:
        if not text:
            continue
        for pat in patterns:
            if pat.search(text):
                return True
    return False
