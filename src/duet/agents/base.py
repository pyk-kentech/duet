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
    round: int = 0   # 구현·리뷰 라운드(1부터, 토론은 비판 라운드). 단계별 추론 강도에 쓴다
    output_schema: dict | None = None    # 구조화 출력 스키마 (DESIGN.md 21.2)
    resume_session: str | None = None    # 이 세션을 이어서 부른다 (DESIGN.md 21.3)
    fallback_prompt: str | None = None   # 이어가기가 실패하면 새 세션으로 보낼 전체 프롬프트
    effort: str | None = None            # 추론 강도를 직접 정함(세션 이어가기는 세션의 강도 유지, DESIGN.md 21.3)


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
    usage: dict | None = None   # input_tokens, output_tokens, cached_input_tokens, cost_usd, model, rate_limits ...
    structured: dict | None = None   # 출력 스키마를 줬을 때 읽은 JSON
    session_id: str | None = None    # CLI 세션 id (이어가기용)
    resumed: bool = False            # 실제로 세션을 이어서 불렀는가 (폴백했으면 False)

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


def should_fall_back(req: "AgentRequest", result: "AgentResult") -> bool:
    """세션 이어가기가 한도·시간 초과가 아닌 이유로 실패했으면 새 세션으로 한 번 더 (DESIGN.md 21.3)."""
    return (bool(req.resume_session) and req.fallback_prompt is not None and not result.ok
            and not result.rate_limited and not result.timed_out)


def fresh_request(req: "AgentRequest") -> "AgentRequest":
    from dataclasses import replace

    return replace(req, prompt=req.fallback_prompt or req.prompt, resume_session=None, fallback_prompt=None)


def parse_structured(text: str) -> dict | None:
    """본문이 JSON 객체면 dict (앞뒤 ``` 울타리는 벗긴다)."""
    import json

    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = s[s.find("{"):] if "{" in s else s
    try:
        data = json.loads(s)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def compile_rate_limit_patterns(patterns: Iterable[str]) -> list[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def detect_rate_limit(texts: Iterable[str], patterns: Iterable[re.Pattern[str]]) -> bool:
    """출력 텍스트들에서 한도 도달 문구가 보이면 True."""
    patterns = list(patterns)
    for text in texts:
        if not text:
            continue
        for pat in patterns:
            if pat.search(text):
                return True
    return False


# 성공한 호출에서 본문만으로 한도를 판단할 때의 최대 길이.
# 정상 응답(설계안, 리뷰)은 이보다 훨씬 길다. 본문이 "rate limit" 을 '언급'만 해도 멈추던 오탐 방지.
SHORT_TEXT_LIMIT = 400
# 실패한 호출에서 진단에 쓰는 stdout/stderr 끝부분 길이 (Codex stdout 에는 대화 전체가 섞인다)
DIAG_TAIL_CHARS = 2000


def classify_rate_limit(
    *,
    failed: bool,
    text: str,
    diagnostics: Iterable[str],
    patterns: Iterable[re.Pattern[str]],
) -> bool:
    """한도 도달 여부.

    - 호출이 실패했으면: stderr/stdout 끝부분과 본문에서 한도 문구를 찾는다.
    - 성공했으면: 본문이 짧을 때만(한도 안내문 자체가 응답인 경우) 본문에서 찾는다.
    """
    patterns = list(patterns)
    if failed:
        tails = [d[-DIAG_TAIL_CHARS:] for d in diagnostics if d]
        if detect_rate_limit([*tails, text[-DIAG_TAIL_CHARS:]], patterns):
            return True
    stripped = text.strip()
    return 0 < len(stripped) <= SHORT_TEXT_LIMIT and detect_rate_limit([stripped], patterns)
