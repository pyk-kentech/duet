"""실시간 작업 보기: 에이전트가 지금 무엇을 하는지(파일 읽기·수정·명령·메시지).

duet 는 CLI 호출 방식을 바꾸지 않고, 두 CLI 가 실시간으로 남기는 자체 세션 기록을 읽는다.
- Claude Code: ~/.claude/projects/<작업 폴더를 '-' 로 바꾼 이름>/<세션>.jsonl 의 assistant 메시지(tool_use, text)
- Codex:       ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl 의 custom_tool_call/function_call, assistant message
로컬 파일만 읽으므로 사용량이 들지 않는다.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from duet.usage import _parse_ts, _session_files, claude_home

MAX_EVENTS = 60
TEXT_LIMIT = 300
_CMD_RE = re.compile(r"""\bcmd\s*:\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)""")
_PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", re.MULTILINE)


def _short(s: str, n: int = TEXT_LIMIT) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _event(ts: Any, kind: str, text: str, detail: str = "") -> dict[str, Any]:
    t = _parse_ts(ts)
    return {"ts": t.isoformat(timespec="seconds") if t else None, "kind": kind, "text": _short(text),
            "detail": _short(detail, 200) if detail else ""}


# ====================================================================== claude
def claude_project_dir(cwd: Path, home: Path | None = None) -> Path:
    name = re.sub(r"[^A-Za-z0-9]", "-", str(Path(cwd).resolve()))
    return (home or claude_home()) / "projects" / name


def _claude_session_file(cwd: Path, since: float, home: Path | None) -> Path | None:
    d = claude_project_dir(cwd, home)
    if d.is_dir():
        files = [p for p in d.glob("*.jsonl") if p.stat().st_mtime >= since - 2]
        return max(files, key=lambda p: p.stat().st_mtime) if files else None
    # 폴더 이름 규칙이 다를 때를 대비: 최근에 바뀐 세션 기록 중 cwd 가 같은 것을 찾는다
    want = str(Path(cwd).resolve())
    root = (home or claude_home()) / "projects"
    if not root.is_dir():
        return None
    recent = sorted((p for p in root.glob("*/*.jsonl") if p.stat().st_mtime >= since - 2),
                    key=lambda p: p.stat().st_mtime, reverse=True)[:20]
    for path in recent:
        for o in _jsonl_tail(path, max_bytes=200_000):
            if o.get("cwd"):
                if o["cwd"] == want:
                    return path
                break
    return None


def claude_activity(cwd: Path, since: float, home: Path | None = None) -> list[dict[str, Any]]:
    path = _claude_session_file(cwd, since, home)
    if path is None:
        return []
    events: list[dict[str, Any]] = []
    for o in _jsonl_tail(path):
        ts = _parse_ts(o.get("timestamp"))
        if ts is None or ts.timestamp() < since - 2:
            continue
        msg = o.get("message")
        if o.get("type") != "assistant" or not isinstance(msg, dict):
            continue
        for c in msg.get("content") or []:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use":
                events.append(_claude_tool(o.get("timestamp"), c.get("name") or "", c.get("input") or {}))
            elif c.get("type") == "text" and str(c.get("text", "")).strip():
                events.append(_event(o.get("timestamp"), "message", c["text"]))
    return events[-MAX_EVENTS:]


def _claude_tool(ts: Any, name: str, inp: dict[str, Any]) -> dict[str, Any]:
    if name in ("Read", "NotebookRead"):
        return _event(ts, "read", inp.get("file_path") or inp.get("notebook_path") or "")
    if name in ("Edit", "MultiEdit", "Write", "NotebookEdit"):
        return _event(ts, "edit", inp.get("file_path") or inp.get("notebook_path") or "", "새로 씀" if name == "Write" else "")
    if name == "Bash":
        return _event(ts, "command", inp.get("command") or "", inp.get("description") or "")
    if name in ("Glob", "Grep"):
        return _event(ts, "search", f"{name} {inp.get('pattern') or ''}", inp.get("path") or "")
    return _event(ts, "tool", name, json.dumps(inp, ensure_ascii=False)[:200])


# ====================================================================== codex
def codex_activity(cwd: Path, since: float, home: Path | None = None) -> list[dict[str, Any]]:
    want = str(Path(cwd).resolve())
    for path in _session_files(since - 2, home):
        events: list[dict[str, Any]] = []
        matched = False
        for o in _jsonl_tail(path):
            t, p = o.get("type"), o.get("payload") or {}
            if t == "session_meta":
                matched = p.get("cwd") == want
                if not matched:
                    break
                continue
            ts = _parse_ts(o.get("timestamp"))
            if ts is None or ts.timestamp() < since - 2:
                continue
            kind = p.get("type")
            if kind in ("custom_tool_call", "function_call"):
                events.extend(_codex_tool(o.get("timestamp"), p))
            elif kind == "message" and p.get("role") == "assistant":
                text = "".join(c.get("text", "") for c in p.get("content") or [] if isinstance(c, dict))
                if text.strip():
                    events.append(_event(o.get("timestamp"), "message", text))
        if matched:
            return events[-MAX_EVENTS:]
    return []


def _codex_tool(ts: Any, p: dict[str, Any]) -> list[dict[str, Any]]:
    raw = p.get("input") or p.get("arguments") or ""
    if not isinstance(raw, str):
        raw = json.dumps(raw, ensure_ascii=False)
    out: list[dict[str, Any]] = []
    for f in _PATCH_FILE_RE.findall(raw):
        out.append(_event(ts, "edit", f.strip()))
    for m in _CMD_RE.findall(raw):
        try:
            cmd = json.loads(m) if m.startswith('"') else m[1:-1]
        except ValueError:
            cmd = m[1:-1]
        out.append(_event(ts, "command", cmd))
    if not out:
        # 예: {"command": ["bash","-lc","..."]} 형태의 function_call
        try:
            args = json.loads(raw)
            cmd = args.get("command") or args.get("cmd")
            if isinstance(cmd, list):
                cmd = cmd[-1]
            if cmd:
                out.append(_event(ts, "command", str(cmd)))
        except (ValueError, AttributeError):
            pass
    if not out:
        out.append(_event(ts, "tool", p.get("name") or "도구", raw[:200]))
    return out


# ====================================================================== 공통
def agent_activity(agent: str, cwd: Path, since: float) -> list[dict[str, Any]]:
    base = agent.replace("mock-", "")
    if base == "claude":
        return claude_activity(cwd, since)
    if base == "codex":
        return codex_activity(cwd, since)
    return []


def _jsonl_tail(path: Path, max_bytes: int = 3_000_000):
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()
            data = f.read().decode("utf-8", errors="replace")
    except OSError:
        return
    for line in data.splitlines():
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if isinstance(o, dict):
            yield o


def call_start_epoch(started_hhmmss: str, now: dt.datetime | None = None) -> float:
    """console.log 의 'HH:MM:SS 실행 중' 시각을 오늘(자정 넘김 고려) epoch 로."""
    now = now or dt.datetime.now()
    h, m, s = (int(x) for x in started_hhmmss.split(":"))
    t = now.replace(hour=h, minute=m, second=s, microsecond=0)
    if t > now:
        t -= dt.timedelta(days=1)
    return t.timestamp()
