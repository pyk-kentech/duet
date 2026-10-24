"""화면 규칙: 터미널 출력 끝부분에 정규식을 대어 상태를 정한다 (DESIGN.md 36.19, herdr 의 아이디어).

훅이 없거나(Codex 승인) 훅이 오래 조용할 때 쓴다. CLI 화면은 버전마다 바뀌므로 내장 규칙은 보수적으로 두고,
`$TENURE_HOME/screen_rules.toml` 로 더하거나(같은 id 면 바꿈) 끌 수 있다:

    [[rules]]
    id = "claude-permission"     # 내장 규칙을 바꿈
    agent = "claude"             # claude | codex | *
    state = "blocked"            # blocked(나를 기다림) | working | idle
    regex = "Do you want to"
    lines = 15                   # 끝에서 몇 줄을 볼지
    priority = 100               # 높은 것부터
    approve = "\\r"              # 승인 키 (blocked 만)
    deny = "\\u001b"             # 거절 키
    enabled = true
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

RULES_FILE = "screen_rules.toml"
STATES = ("blocked", "working", "idle")
TAIL_CHARS = 16_000
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class RuleError(Exception):
    pass


@dataclass(frozen=True)
class Rule:
    id: str
    state: str
    regex: str
    agent: str = "*"
    lines: int = 12
    priority: int = 0
    approve: str = ""
    deny: str = ""
    enabled: bool = True
    source: str = "내장"

    def compiled(self) -> re.Pattern:
        return re.compile(self.regex, re.M | re.I)


BUILTIN: tuple[Rule, ...] = (
    Rule("claude-permission", "blocked", r"Do you want to (proceed|make this edit|create|allow|run)|Allow .* to (run|use)",
         agent="claude", lines=15, priority=100, approve="\r", deny="\x1b"),
    Rule("claude-working", "working", r"esc to interrupt", agent="claude", lines=6, priority=50),
    Rule("codex-approval", "blocked", r"Allow command\?|Would you like to (run|make|apply)|Approve .*\?|Yes, proceed",
         agent="codex", lines=15, priority=100, approve="y", deny="\x1b"),
    Rule("codex-working", "working", r"esc to interrupt|Working \(", agent="codex", lines=6, priority=50),
    Rule("generic-yes-no", "blocked", r"\((y/n|Y/n|y/N)\)|\[(y/n|Y/n|y/N)\]\s*$", lines=4, priority=20,
         approve="y\r", deny="n\r"),
)


def clean(text: str) -> str:
    text = ANSI_RE.sub("", text.replace("\r\n", "\n"))
    return text.replace("\r", "\n")


def tail_lines(text: str, lines: int) -> str:
    """출력 끝부분에서 제어 문자를 지운 마지막 N줄(빈 줄 제외)."""
    rows = [ln.rstrip() for ln in clean(text[-TAIL_CHARS:]).split("\n") if ln.strip()]
    return "\n".join(rows[-lines:])


def _decode(v: object) -> str:
    return v.encode("utf-8").decode("unicode_escape") if isinstance(v, str) else ""


def load_rules(home: Path | None) -> list[Rule]:
    rules = {r.id: r for r in BUILTIN}
    path = Path(home) / RULES_FILE if home else None
    if path is not None and path.is_file():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise RuleError(f"{path} 를 읽을 수 없습니다: {e}") from e
        for i, d in enumerate(data.get("rules") or [], 1):
            if not isinstance(d, dict) or not isinstance(d.get("id"), str):
                raise RuleError(f"{path}: {i}번째 규칙에 id 가 없습니다")
            base = rules.get(d["id"])
            fields = {k: d[k] for k in ("state", "regex", "agent", "lines", "priority", "enabled") if k in d}
            for k in ("approve", "deny"):
                if k in d:
                    fields[k] = _decode(d[k])
            if base is not None:
                rule = replace(base, **fields, source="사용자")
            elif "state" in fields and "regex" in fields:
                rule = Rule(id=d["id"], **fields, source="사용자")
            else:
                raise RuleError(f"{path}: 새 규칙 {d['id']} 에는 state 와 regex 가 필요합니다")
            if rule.state not in STATES:
                raise RuleError(f"{path}: 규칙 {rule.id} 의 state 는 {', '.join(STATES)} 중 하나여야 합니다")
            try:
                rule.compiled()
            except re.error as e:
                raise RuleError(f"{path}: 규칙 {rule.id} 의 정규식이 잘못되었습니다: {e}") from e
            rules[rule.id] = rule
    return sorted((r for r in rules.values() if r.enabled), key=lambda r: -r.priority)


def match(rules: list[Rule], agent: str, text: str) -> tuple[Rule, str] | None:
    """맞은 규칙과 그 규칙이 본 화면 끝부분. 우선순위가 높은 것부터."""
    for r in rules:
        if r.agent not in ("*", agent):
            continue
        region = tail_lines(text, r.lines)
        if region and r.compiled().search(region):
            return r, region
    return None
