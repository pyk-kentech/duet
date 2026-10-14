"""에이전트 어댑터 모음과 팩토리."""

from __future__ import annotations

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
    """이름("claude", "codex") → 어댑터 매핑을 만든다."""
    if mock:
        return dict(mock_pair())
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
