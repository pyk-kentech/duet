"""에이전트 어댑터 모음과 팩토리."""

from __future__ import annotations

import os

from duet.agents.base import (
    AgentAdapter,
    AgentError,
    AgentNotAvailable,
    AgentRequest,
    AgentResult,
    Mode,
)
from duet.agents.claude_code import ClaudeCodeAdapter
from duet.agents.codex import CodexAdapter
from duet.agents.mock import MockAdapter, mock_pair
from duet.config import AGENT_NAMES, Config


def make_agents(cfg: Config, *, mock: bool = False) -> dict[str, AgentAdapter]:
    """이름("claude", "codex") → 어댑터 매핑을 만든다.

    mock 일 때 환경변수 DUET_MOCK_DELAY(초)를 주면 호출마다 그만큼 쉰다(UI 확인·중지 테스트용).
    """
    if mock:
        try:
            delay = float(os.environ.get("DUET_MOCK_DELAY", "0") or 0)
        except ValueError:
            delay = 0.0
        return dict(mock_pair(delay_sec=delay))
    return {
        "claude": ClaudeCodeAdapter(cfg),
        "codex": CodexAdapter(cfg),
    }


__all__ = [
    "AGENT_NAMES",
    "AgentAdapter",
    "AgentError",
    "AgentNotAvailable",
    "AgentRequest",
    "AgentResult",
    "ClaudeCodeAdapter",
    "CodexAdapter",
    "Mode",
    "MockAdapter",
    "make_agents",
    "mock_pair",
]
