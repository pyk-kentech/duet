"""워크플로 자동 선택 `auto` (DESIGN.md 36.5).

먼저 규칙(공짜)으로 정하고, 애매하면 작은 모델(haiku)에 한 번 묻는다. 벤치마크(34.2·35장) 결론: 요구가 분명하면
설계 토론이 정확도를 못 올리고 비용만 늘린다 → 기본은 quick, 짧고 모호한 새 프로젝트만 classic(설계 토론).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

QUICK = "quick"
CLASSIC = "classic"
SHORT_TASK = 200          # 이보다 짧은 새 프로젝트 과제는 설계 결정이 많이 남는다
DETAILED_TASK = 600       # 이보다 길면 요구가 충분히 적혀 있다고 본다
ROUTER_MODEL = "claude-haiku-5-5"
_IGNORE = {".git", ".tenure", ".duet", "tenure.toml", "duet.toml", ".gitignore", "README.md", "readme.md"}
_STRUCTURE_RE = re.compile(r"^\s*(?:[-*]|\d+[.)]|#{1,6})\s+", re.M)


@dataclass
class Route:
    workflow: str
    reason: str
    source: str            # "rule" | "model" | "fallback"

    def to_dict(self) -> dict:
        return {"workflow": self.workflow, "reason": self.reason, "source": self.source}


def has_existing_code(workdir: Path) -> bool:
    try:
        return any(p.name not in _IGNORE for p in Path(workdir).iterdir())
    except OSError:
        return False


def rule_route(task: str, workdir: Path) -> Route | None:
    text = task.strip()
    if has_existing_code(workdir):
        return Route(QUICK, "기존 프로젝트를 바꾸는 일", "rule")
    structured = len(_STRUCTURE_RE.findall(text)) >= 3
    if len(text) >= DETAILED_TASK or (structured and len(text) >= SHORT_TASK):
        return Route(QUICK, "요구가 충분히 적힌 새 프로젝트", "rule")
    if len(text) < SHORT_TASK and not structured:
        return Route(CLASSIC, "짧고 열린 새 프로젝트 과제 — 설계 결정이 많이 남음", "rule")
    return None


PROMPT = """너는 작업 분류기다. 아래 소프트웨어 과제를 보고 어떤 진행 방식이 맞는지 하나만 골라라.
- quick: 요구가 분명해서 바로 구현하면 되는 일 (구현 → 리뷰)
- classic: 설계 결정이 크고 여러 가지라 먼저 두 모델이 설계를 토론하는 게 나은 일
파일을 읽거나 만들지 말고, 아래 형식의 JSON 한 줄만 답하라.
{{"route": "quick" 또는 "classic", "reason": "한국어 한 문장"}}

과제:
{task}
"""


def model_route(task: str, workdir: Path, cfg) -> Route:
    """haiku 에 한 번 묻는다. 실패하면 quick."""
    from tenure.agents.base import AgentRequest, Mode
    from tenure.agents.claude_code import ClaudeCodeAdapter

    try:
        adapter = ClaudeCodeAdapter(cfg, replace(cfg.claude, model=ROUTER_MODEL))
        res = adapter.ask(AgentRequest(prompt=PROMPT.format(task=task.strip()[:6000]), cwd=Path(workdir),
                                       mode=Mode.READ, timeout_sec=120, step="route", effort="low"))
        m = re.search(r"\{.*\}", res.text or "", re.S)
        data = json.loads(m.group(0)) if (res.ok and m) else {}
        route = str(data.get("route", "")).strip().lower()
        if route in (QUICK, CLASSIC):
            return Route(route, str(data.get("reason") or "").strip()[:200] or "작은 모델의 판단", "model")
    except Exception:  # noqa: BLE001 — 분류 실패는 실행을 막지 않는다
        pass
    return Route(QUICK, "분류에 실패해 기본값(quick)", "fallback")


def choose(task: str, workdir: Path, cfg, *, mock: bool = False) -> Route:
    r = rule_route(task, workdir)
    if r is not None:
        return r
    if mock:
        return Route(QUICK, "규칙으로 정하지 못함 — mock 이라 모델에 묻지 않고 quick", "fallback")
    return model_route(task, workdir, cfg)
