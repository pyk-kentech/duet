"""단계 결과 계약과 실행의 주의 상태 (DESIGN.md 36.3).

- 단계(에이전트 호출 한 번)는 done / blocked / failed / unconfirmed 와 이유로 끝난다. 조용한 실패는 없다.
- 실행은 화면이 정렬·표시할 활동 상태를 가진다: blocked(나를 기다림) > done-unseen(끝났는데 안 봄) >
  working > idle, 그 밖에 failed·unverifiable(살아 있는데 소식이 끊김).
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

# 단계 결과
DONE = "done"
BLOCKED = "blocked"
FAILED = "failed"
UNCONFIRMED = "unconfirmed"     # 끝났지만 기대한 구조화 결과가 없음

# 실행 활동
WORKING = "working"
DONE_UNSEEN = "done-unseen"
IDLE = "idle"
UNVERIFIABLE = "unverifiable"
RANK = {BLOCKED: 4, DONE_UNSEEN: 3, WORKING: 2, UNVERIFIABLE: 2, FAILED: 1, IDLE: 0}

STALL_SEC = 15 * 60             # 이벤트가 이만큼 없으면 '소식 끊김' (긴 구현 한 번이 10분을 넘기도 한다)

_AUTH_RE = re.compile(r"not logged in|please (?:log|sign) ?in|login required|run .*login|authenticat\w* (?:failed|error|required)"
                      r"|unauthori[sz]ed|\b401\b|invalid api key|credentials? (?:expired|missing)", re.I)
_TRUST_RE = re.compile(r"trust (?:this|the) (?:folder|directory)|untrusted (?:folder|directory)", re.I)
_UPDATE_RE = re.compile(r"(?:must|need to|please) (?:update|upgrade)|update required|version .* no longer supported", re.I)


def step_outcome(result, *, expect_structured: bool = False) -> tuple[str, str]:
    """AgentResult → (결과, 이유). 이유는 화면에 그대로 보인다(한국어)."""
    if result.rate_limited:
        return BLOCKED, "구독 한도"
    tail = f"{getattr(result, 'raw_stderr', '')}\n{getattr(result, 'text', '')}"[-6000:]
    if not result.ok:
        if result.timed_out:
            return FAILED, "시간 초과"
        if _AUTH_RE.search(tail):
            return BLOCKED, "로그인 필요"
        if _TRUST_RE.search(tail):
            return BLOCKED, "폴더 신뢰 필요"
        if _UPDATE_RE.search(tail):
            return BLOCKED, "CLI 업데이트 필요"
        return FAILED, result.failure_reason()
    if expect_structured and result.structured is None:
        return UNCONFIRMED, "구조화 결과 없음(본문으로 대신 읽음)"
    return DONE, ""


def _parse(ts: str | None) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(ts) if ts else None
    except ValueError:
        return None


def run_activity(state: dict[str, Any], *, live: bool, last_ts: str | None = None,
                 now: dt.datetime | None = None) -> dict[str, Any]:
    """실행 하나의 활동 상태 {state, reason, rank}. state 는 run.json 의 dict, live 는 잠금이 살아 있는가."""
    now = now or dt.datetime.now()
    status = str(state.get("status") or "")
    seen = _parse(state.get("seen_at"))
    last = _parse(last_ts)

    def out(kind: str, reason: str = "") -> dict[str, Any]:
        return {"state": kind, "reason": reason, "rank": RANK[kind]}

    if status == "running":
        if not live:
            return out(FAILED, "프로세스가 끝났는데 실행이 '진행 중'으로 남음")
        wait = state.get("limit_wait") or {}
        if wait:
            return out(BLOCKED, f"구독 한도 대기 ({wait.get('until', '')[11:16]} 까지)")
        if last and (now - last).total_seconds() > STALL_SEC:
            return out(UNVERIFIABLE, f"{int((now - last).total_seconds() // 60)}분째 소식 없음")
        return out(WORKING)
    if status == "stopped_rate_limit":
        return out(BLOCKED, "구독 한도로 멈춤 — 이어하기")
    if status == "failed":
        return out(FAILED, str(state.get("error") or "실패"))
    if status == "stopped_user":
        return out(IDLE, "중지함")
    if status in ("done_approved", "done_unapproved", "done_design"):
        if seen is None or (last is not None and last > seen):
            reason = {"done_approved": "승인으로 끝남", "done_unapproved": "미승인으로 멈춤 — 확인 필요",
                      "done_design": "설계까지 끝남"}[status]
            return out(DONE_UNSEEN, reason)
        return out(IDLE)
    return out(IDLE)
