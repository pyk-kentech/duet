"""세션 훅 (DESIGN.md 36.19): CLI 가 상태가 바뀔 때 부르는 명령을 호출마다 붙인다(사용자 설정 파일은 안 고침).

- Claude: `--settings <JSON>` 의 hooks (SessionStart·UserPromptSubmit·Notification·Stop).
  PreToolUse 는 붙이지 않는다: 도구 호출마다 파이썬을 띄워 0.1~0.2초씩 늦어진다. 승인 뒤 다시 일하는 것은 화면으로 안다.
- Codex: `-c notify=[...]` (턴이 끝날 때, 마지막 인자로 JSON).
훅 명령은 `python -m tenure _hook <세션 폴더> <nonce> <이벤트>` 로 hooks.jsonl 에 한 줄 쓰고 아무것도 출력하지 않는다
(UserPromptSubmit 훅의 출력은 대화에 들어가므로).
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

HOOKS_FILE = "hooks.jsonl"
CLAUDE_EVENTS = ("SessionStart", "UserPromptSubmit", "Notification", "Stop")
CODEX_EVENT = "codex-notify"
KEEP = ("hook_event_name", "notification_type", "message", "type", "last-assistant-message", "turn-id", "session_id")
MAX_FIELD = 500


def _cmd(session_dir: Path, nonce: str) -> list[str]:
    return [Path(sys.executable).as_posix(), "-m", "tenure", "_hook", Path(session_dir).as_posix(), nonce]


def claude_settings(session_dir: Path, nonce: str) -> str:
    base = " ".join(f'"{x}"' if " " in x else x for x in _cmd(session_dir, nonce))
    hooks = {ev: [{"hooks": [{"type": "command", "command": f"{base} {ev}", "timeout": 10}]}] for ev in CLAUDE_EVENTS}
    return json.dumps({"hooks": hooks}, ensure_ascii=False)


def codex_args(session_dir: Path, nonce: str) -> list[str]:
    items = ",".join(f"'{x}'" for x in [*_cmd(session_dir, nonce), CODEX_EVENT])   # TOML 리터럴 문자열(역슬래시 그대로)
    return ["-c", f"notify=[{items}]"]


CHAIN_ENV = "TENURE_CHAIN_NOTIFY"


def user_codex_notify() -> list[str]:
    """사용자의 ~/.codex/config.toml 의 notify (읽기만). 세션의 -c notify 가 덮어쓰므로 우리 훅이 이어서 부른다."""
    from tenure.usage import codex_home
    try:
        import tomllib
        v = tomllib.loads((codex_home() / "config.toml").read_text(encoding="utf-8")).get("notify")
    except (OSError, ValueError):
        return []
    return [str(x) for x in v] if isinstance(v, list) and all(isinstance(x, str) for x in v) else []


def chain_notify(payload: str | None) -> None:
    """사용자가 원래 쓰던 Codex notify 명령도 부른다(기다리지 않음)."""
    import os
    raw = os.environ.get(CHAIN_ENV)
    if not raw:
        return
    try:
        cmd = json.loads(raw)
    except ValueError:
        return
    if not (isinstance(cmd, list) and cmd and all(isinstance(x, str) for x in cmd)):
        return
    from tenure.runner import ExecutableNotFound, spawn_detached
    try:
        with open(os.devnull, "wb") as null:
            spawn_detached([*cmd, payload or "{}"], os.getcwd(), log_file=null)
    except (ExecutableNotFound, OSError):
        pass


def record(session_dir: Path, nonce: str, event: str, payload: str | None) -> None:
    """훅 명령의 본체: 받은 JSON 에서 필요한 칸만 남겨 한 줄 쓴다."""
    try:
        data = json.loads(payload) if payload else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    keep = {k: (str(v)[:MAX_FIELD] if not isinstance(v, (int, float, bool)) else v) for k, v in data.items() if k in KEEP}
    line = {"ts": dt.datetime.now().isoformat(timespec="milliseconds"), "nonce": nonce, "event": event, "data": keep}
    path = Path(session_dir) / HOOKS_FILE
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


def read_new(session_dir: Path, offset: int, nonce: str) -> tuple[list[dict[str, Any]], int]:
    """offset 바이트 뒤의 훅 기록 중 nonce 가 맞는 것. (기록, 새 offset)"""
    path = Path(session_dir) / HOOKS_FILE
    try:
        with path.open("rb") as f:
            f.seek(offset)
            raw = f.read()
    except OSError:
        return [], offset
    end = raw.rfind(b"\n") + 1               # 쓰는 중인 마지막 줄은 다음에
    out = []
    for line in raw[:end].splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("nonce") == nonce:
            out.append(ev)
    return out, offset + end


def interpret(ev: dict[str, Any]) -> tuple[str, str]:
    """훅 기록 → (상태, 이유). 상태는 blocked | working | idle."""
    name, data = ev.get("event"), ev.get("data") or {}
    if name == "UserPromptSubmit":
        return "working", "요청을 받아 일하는 중"
    if name == "Notification":
        kind = str(data.get("notification_type") or "")
        msg = str(data.get("message") or "")
        if kind == "permission_prompt" or "permission" in msg.lower():
            return "blocked", msg or "승인 필요"
        return "idle", msg or "입력을 기다림"
    if name == "Stop":
        return "idle", "턴이 끝남"
    if name == CODEX_EVENT:
        return "idle", "턴이 끝남"
    if name == "SessionStart":
        return "idle", "입력을 기다림"
    return "working", str(name)
