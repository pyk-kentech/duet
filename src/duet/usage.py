"""사용량 수집.

- Claude: `claude -p --output-format json` 응답의 usage / total_cost_usd / modelUsage.
  구독 한도(%)는 CLI 가 알려주지 않으므로, ~/.claude/projects/*.jsonl 의 메시지 사용량을 모아
  최근 5시간·7일 토큰을 보여준다(duet 밖의 Claude Code 사용 포함).
- Codex: `codex exec` 가 남기는 세션 기록(~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl)의
  token_count 이벤트. 여기에 구독 한도 사용률(rate_limits)도 들어 있다.

모두 로컬 파일만 읽는다. 구독 사용량을 쓰지 않는다.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Iterable

CLAUDE_WINDOWS = (("5시간", 5 * 3600), ("7일", 7 * 86400))


# ====================================================================== claude
def claude_call_usage(data: dict[str, Any]) -> dict[str, Any] | None:
    """claude -p JSON 결과에서 이번 호출의 사용량."""
    u = data.get("usage")
    if not isinstance(u, dict):
        return None
    cache_read = int(u.get("cache_read_input_tokens") or 0)
    cache_write = int(u.get("cache_creation_input_tokens") or 0)
    out = {
        "input_tokens": int(u.get("input_tokens") or 0) + cache_read + cache_write,
        "cached_input_tokens": cache_read,
        "output_tokens": int(u.get("output_tokens") or 0),
    }
    details = u.get("output_tokens_details") or {}
    if isinstance(details, dict) and details.get("thinking_tokens"):
        out["reasoning_tokens"] = int(details["thinking_tokens"])
    if isinstance(data.get("total_cost_usd"), (int, float)):
        out["cost_usd"] = round(float(data["total_cost_usd"]), 4)
    models = data.get("modelUsage")
    if isinstance(models, dict) and models:
        out["model"] = ", ".join(sorted(models))
    return out


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def claude_local_usage(now: dt.datetime | None = None, home: Path | None = None) -> dict[str, Any]:
    """최근 5시간·7일 동안 이 머신의 Claude Code 가 쓴 토큰 (모든 세션 기록 합산)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    root = (home or claude_home()) / "projects"
    horizon = now.timestamp() - max(w for _, w in CLAUDE_WINDOWS)
    seen: set[str] = set()
    totals = {name: {"input_tokens": 0, "output_tokens": 0, "messages": 0} for name, _ in CLAUDE_WINDOWS}
    by_model: dict[str, int] = {}
    files = 0
    if root.is_dir():
        for path in root.glob("*/*.jsonl"):
            try:
                if path.stat().st_mtime < horizon:
                    continue
            except OSError:
                continue
            files += 1
            for o in _jsonl(path):
                msg = o.get("message")
                if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
                    continue
                key = str(o.get("requestId") or msg.get("id") or o.get("uuid"))
                if key in seen:
                    continue
                ts = _parse_ts(o.get("timestamp"))
                if ts is None or ts.timestamp() < horizon:
                    continue
                seen.add(key)
                u = msg["usage"]
                inp = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
                outp = int(u.get("output_tokens") or 0)
                age = now.timestamp() - ts.timestamp()
                for name, window in CLAUDE_WINDOWS:
                    if age <= window:
                        totals[name]["input_tokens"] += inp
                        totals[name]["output_tokens"] += outp
                        totals[name]["messages"] += 1
                model = msg.get("model")
                if model and age <= CLAUDE_WINDOWS[-1][1]:
                    by_model[model] = by_model.get(model, 0) + outp
    return {"windows": totals, "output_by_model_7d": by_model, "files": files,
            "as_of": now.isoformat(timespec="seconds")}


# ====================================================================== codex
def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def _session_files(since: float, home: Path | None = None, days: int = 2) -> list[Path]:
    base = (home or codex_home()) / "sessions"
    out: list[Path] = []
    today = dt.date.today()
    for d in range(days):
        day = today - dt.timedelta(days=d)
        folder = base / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"
        if not folder.is_dir():
            continue
        for p in folder.glob("rollout-*.jsonl"):
            try:
                if p.stat().st_mtime >= since:
                    out.append(p)
            except OSError:
                pass
    out.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return out


def codex_call_usage(cwd: Path, since: float, home: Path | None = None) -> dict[str, Any] | None:
    """since(epoch) 이후 cwd 에서 돈 codex exec 세션의 사용량. 못 찾으면 None."""
    want = str(Path(cwd).resolve())
    for path in _session_files(since - 2, home):
        meta_cwd = None
        model = effort = None
        last = None
        for o in _jsonl(path):
            t, p = o.get("type"), o.get("payload") or {}
            if t == "session_meta":
                meta_cwd = p.get("cwd")
                started = _parse_ts(p.get("timestamp") or o.get("timestamp"))
                if meta_cwd != want or (started and started.timestamp() < since - 5):
                    break
            elif t == "turn_context":
                model, effort = p.get("model") or model, p.get("effort") or p.get("reasoning_effort") or effort
            elif p.get("type") == "token_count" and p.get("info"):
                last = p
        if meta_cwd != want or last is None:
            continue
        total = (last.get("info") or {}).get("total_token_usage") or {}
        out = {
            "input_tokens": int(total.get("input_tokens") or 0),
            "cached_input_tokens": int(total.get("cached_input_tokens") or 0),
            "output_tokens": int(total.get("output_tokens") or 0),
            "reasoning_tokens": int(total.get("reasoning_output_tokens") or 0),
        }
        if model:
            out["model"] = model
        if effort:
            out["effort"] = effort
        rl = summarize_rate_limits(last.get("rate_limits"))
        if rl:
            out["rate_limits"] = rl
        return out
    return None


def summarize_rate_limits(rl: Any) -> dict[str, Any] | None:
    if not isinstance(rl, dict):
        return None
    out: dict[str, Any] = {}
    for key in ("primary", "secondary"):
        w = rl.get(key)
        if isinstance(w, dict) and w.get("used_percent") is not None:
            out[key] = {
                "used_percent": float(w["used_percent"]),
                "window_minutes": w.get("window_minutes"),
                "resets_at": w.get("resets_at"),
            }
    if rl.get("plan_type"):
        out["plan_type"] = rl["plan_type"]
    if rl.get("rate_limit_reached_type"):
        out["reached"] = rl["rate_limit_reached_type"]
    return out or None


def codex_rate_limits(home: Path | None = None, days: int = 8) -> dict[str, Any] | None:
    """가장 최근 Codex 세션 기록의 한도 사용률(대화형 사용 포함)."""
    since = (dt.datetime.now() - dt.timedelta(days=days)).timestamp()
    for path in _session_files(since, home, days=days)[:20]:
        latest = None
        for o in _tail_jsonl(path):
            p = o.get("payload") or {}
            if p.get("type") == "token_count" and p.get("rate_limits"):
                latest = (o.get("timestamp"), p["rate_limits"])
        if latest:
            rl = summarize_rate_limits(latest[1])
            if rl:
                rl["as_of"] = latest[0]
                return rl
    return None


# ====================================================================== helpers
def _jsonl(path: Path) -> Iterable[dict[str, Any]]:
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if isinstance(o, dict):
                    yield o
    except OSError:
        return


def _tail_jsonl(path: Path, max_bytes: int = 2_000_000) -> Iterable[dict[str, Any]]:
    """큰 세션 파일은 끝부분만 읽는다."""
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


def _parse_ts(v: Any) -> dt.datetime | None:
    if not isinstance(v, str):
        return None
    try:
        t = dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.astimezone()
    return t


def add_usage(total: dict[str, Any], u: dict[str, Any] | None) -> None:
    if not u:
        return
    for k in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens"):
        total[k] = total.get(k, 0) + int(u.get(k) or 0)
    if u.get("cost_usd"):
        total["cost_usd"] = round(total.get("cost_usd", 0) + float(u["cost_usd"]), 4)
    total["calls"] = total.get("calls", 0) + 1
