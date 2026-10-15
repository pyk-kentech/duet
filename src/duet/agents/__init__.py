"""에이전트 어댑터 모음과 팩토리."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from duet.workflow import Workflow


def _mock_delay() -> float:
    try:
        return float(os.environ.get("DUET_MOCK_DELAY", "0") or 0)
    except ValueError:
        return 0.0


def make_agents(cfg: Config, *, mock: bool = False) -> dict[str, AgentAdapter]:
    """이름("claude", "codex") → 어댑터 매핑을 만든다.

    mock 일 때 환경변수 DUET_MOCK_DELAY(초)를 주면 호출마다 그만큼 쉰다(UI 확인·중지 테스트용).
    """
    if mock:
        return dict(mock_pair(delay_sec=_mock_delay()))
    return {
        "claude": ClaudeCodeAdapter(cfg),
        "codex": CodexAdapter(cfg),
    }


def make_role_agents(cfg: Config, workflow: "Workflow", *, mock: bool = False) -> dict[str, AgentAdapter]:
    """워크플로 역할 이름 → 어댑터. 역할마다 모델·강도가 다른 설정으로 같은 CLI 를 부른다 (DESIGN.md 19.1)."""
    out: dict[str, AgentAdapter] = {}
    for name in workflow.used_roles():
        role = workflow.roles[name]
        if mock:
            out[name] = MockAdapter(label=name, delay_sec=_mock_delay())
        elif role.agent == "claude":
            out[name] = ClaudeCodeAdapter(cfg, role.agent_config(cfg))
        else:
            out[name] = CodexAdapter(cfg, role.agent_config(cfg))
    return out


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
    "make_role_agents",
    "mock_pair",
]
