"""한도 대기 후 자동 재개 (DESIGN.md 25.1).

한도에 걸린 호출의 응답·stderr·사용량에서 재개 시각을 찾고, 못 찾으면 백오프 간격을 쓴다.
"""

from __future__ import annotations

import datetime as dt
import re
import time
from typing import Any, Iterable

MARGIN_SEC = 60
BACKOFF_MIN = (15, 30, 60)          # 이후 60분마다
MIN_WAIT_SEC = 60
MAX_PARSED_SEC = 8 * 24 * 3600      # 이보다 먼 시각은 잘못 읽은 것으로 본다

_EPOCH_RE = re.compile(r"(?:\||resets?_?at\"?\s*[:=]\s*\"?)(1\d{9})(?:\d{3})?\b", re.IGNORECASE)
_UNIT_SEC = {"d": 86400, "h": 3600, "m": 60, "s": 1}
_DURATION_PART = r"\d+(?:\.\d+)?\s*(?:days?|d|hours?|hrs?|hr|h|minutes?|mins?|min|m|seconds?|secs?|sec|s)\b"
_REL_RE = re.compile(
    r"(?:try again|retry|resets?|reset|available again|wait)\s+(?:in|after)\s+"
    r"((?:" + _DURATION_PART + r"(?:\s*,\s*|\s+and\s+|\s+)?)+)", re.IGNORECASE)
_PART_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([a-z]+)", re.IGNORECASE)
_CLOCK_RE = re.compile(
    r"(?:resets?|reset|try again|available again)\s+(?:at\s+|on\s+)?"
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?:\s*\(([A-Za-z_]+/[A-Za-z_/]+|UTC)\))?", re.IGNORECASE)


def _duration_sec(text: str) -> float:
    total = 0.0
    for num, unit in _PART_RE.findall(text):
        key = unit.lower()[0]
        if key in _UNIT_SEC:
            total += float(num) * _UNIT_SEC[key]
    return total


def _tz(name: str | None):
    if not name:
        return None
    if name.upper() == "UTC":
        return dt.timezone.utc
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - tzdata 없음(Windows) 등 → 로컬 시각
        return None


def _clock_epoch(hour: int, minute: int, ampm: str | None, tzname: str | None, now: float) -> float | None:
    if ampm:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if ampm.lower() == "pm" else 0)
    elif not 0 <= hour <= 23:
        return None
    if not 0 <= minute <= 59:
        return None
    tz = _tz(tzname)
    base = dt.datetime.fromtimestamp(now, tz) if tz else dt.datetime.fromtimestamp(now)
    target = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target.timestamp() <= now:
        target += dt.timedelta(days=1)
    return target.timestamp()


def reset_from_text(texts: Iterable[str], now: float) -> float | None:
    """응답·stderr 에서 재개 시각(epoch 초)."""
    for text in texts:
        if not text:
            continue
        m = _EPOCH_RE.search(text)
        if m:
            t = float(m.group(1))
            if now < t <= now + MAX_PARSED_SEC:
                return t
        m = _REL_RE.search(text)
        if m:
            sec = _duration_sec(m.group(1))
            if 0 < sec <= MAX_PARSED_SEC:
                return now + sec
        for m in _CLOCK_RE.finditer(text):
            if m.group(2) is None and m.group(3) is None:
                continue                  # "reset at 5" 처럼 숫자만이면 시각인지 알 수 없다
            t = _clock_epoch(int(m.group(1)), int(m.group(2) or 0), m.group(3), m.group(4), now)
            if t is not None:
                return t
    return None


def reset_from_usage(usage: dict[str, Any] | None, now: float) -> float | None:
    """Codex 사용량 기록의 rate_limits: 사용률 100% 인 창의 resets_at."""
    rl = (usage or {}).get("rate_limits")
    if not isinstance(rl, dict):
        return None
    times = []
    if rl.get("status") == "rejected" and rl.get("resets_at"):     # Claude rate_limit_event (DESIGN.md 28.6)
        try:
            t = float(rl["resets_at"])
            if now < t <= now + MAX_PARSED_SEC:
                times.append(t)
        except (TypeError, ValueError):
            pass
    for w in rl.values():                      # Codex primary/secondary, Claude five_hour/seven_day
        if isinstance(w, dict) and float(w.get("used_percent") or 0) >= 100 and w.get("resets_at"):
            try:
                t = float(w["resets_at"])
            except (TypeError, ValueError):
                continue
            if now < t <= now + MAX_PARSED_SEC:
                times.append(t)
    return max(times) if times else None


def plan_wait(texts: Iterable[str], usage: dict[str, Any] | None, hits: int, now: float) -> tuple[float, str]:
    """(기다릴 초, 근거). hits: 이 호출에서 한도에 걸린 횟수(1부터, 백오프 단계)."""
    texts = list(texts)
    t = reset_from_text(texts, now)
    if t is not None:
        return max(MIN_WAIT_SEC, t - now + MARGIN_SEC), "메시지의 재개 시각"
    t = reset_from_usage(usage, now)
    if t is not None:
        return max(MIN_WAIT_SEC, t - now + MARGIN_SEC), "사용량 기록의 재개 시각"
    minutes = BACKOFF_MIN[min(hits, len(BACKOFF_MIN)) - 1]
    return minutes * 60.0, f"재개 시각을 몰라 {minutes}분 뒤 다시 시도"


def sleep(seconds: float) -> None:
    """테스트에서 바꿔 끼운다. 짧게 나눠 자서 Ctrl-C·SIGTERM 에 바로 반응한다."""
    from duet import stopflag

    end = time.monotonic() + seconds
    while True:
        stopflag.check()                          # UI 의 중지 요청 (DESIGN.md 27.3)
        left = end - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(left, stopflag.POLL_SEC if stopflag.active() else 30.0))


def now() -> float:
    return time.time()
