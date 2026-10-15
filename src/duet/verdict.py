"""리뷰 판정 파싱.

우선 형식:
    <verdict>
    status: APPROVED | CHANGES_REQUESTED
    must_fix: 3
    </verdict>
레거시 형식: `VERDICT: APPROVED` 한 줄.
둘 다 없으면 CHANGES_REQUESTED 로 간주하고 parse_failed=True.
status: APPROVED 인데 must_fix > 0 이면 모순 → CHANGES_REQUESTED, contradiction=True.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Status(Enum):
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


@dataclass(frozen=True)
class Verdict:
    status: Status
    must_fix: int | None = None
    source: str = "none"          # "block" | "legacy" | "none"
    parse_failed: bool = False
    contradiction: bool = False
    severity: dict[str, int] | None = None   # {"P1": n, "P2": n, "P3": n} (리뷰어가 적었을 때만)

    @property
    def approved(self) -> bool:
        return self.status is Status.APPROVED

    def describe(self) -> str:
        s = self.status.value
        notes = []
        if self.must_fix is not None:
            notes.append(f"must_fix={self.must_fix}")
        if self.severity:
            notes.append(" ".join(f"{k}={v}" for k, v in self.severity.items()))
        if self.parse_failed:
            notes.append("판정 블록 없음 → 반려로 간주")
        if self.contradiction:
            notes.append("APPROVED인데 must_fix>0 → 반려로 처리")
        return s + (f" ({', '.join(notes)})" if notes else "")


_BLOCK_RE = re.compile(r"<verdict>(.*?)</verdict>", re.IGNORECASE | re.DOTALL)
_LIST = r"(?:[-*+>]\s*|\d+[.)]\s*)?"
_STATUS_RE = re.compile(r"^\s*" + _LIST + r"status\s*:\s*(APPROVED|CHANGES_REQUESTED)\b",
                        re.IGNORECASE | re.MULTILINE)
_MUST_FIX_RE = re.compile(r"^\s*" + _LIST + r"must_fix\s*:\s*(\d+)", re.IGNORECASE | re.MULTILINE)
_SEV_RE = re.compile(r"^\s*" + _LIST + r"(p[123])\s*:\s*(\d+)", re.IGNORECASE | re.MULTILINE)
_LEGACY_RE = re.compile(r"VERDICT\s*:\s*(APPROVED|CHANGES_REQUESTED)\b", re.IGNORECASE)
# 모델이 즐겨 붙이는 강조 기호: **status:** APPROVED, `APPROVED` (밑줄은 CHANGES_REQUESTED 의 일부라 건드리지 않음)
_DECORATION_RE = re.compile(r"[*`]")


def _plain(text: str) -> str:
    return _DECORATION_RE.sub("", text)


def parse_verdict(text: str) -> Verdict:
    """리뷰 응답 전체에서 판정을 뽑는다. 여러 개면 마지막 것을 쓴다."""
    blocks = _BLOCK_RE.findall(text or "")
    for body in reversed(blocks):
        body = _plain(body)
        m = _STATUS_RE.search(body)
        if not m:
            continue
        status = Status(m.group(1).upper())
        mf = _MUST_FIX_RE.search(body)
        must_fix = int(mf.group(1)) if mf else None
        sev = {k.upper(): int(v) for k, v in _SEV_RE.findall(body)} or None
        if status is Status.APPROVED and must_fix:
            return Verdict(Status.CHANGES_REQUESTED, must_fix, "block", contradiction=True, severity=sev)
        return Verdict(status, must_fix, "block", severity=sev)

    legacy = _LEGACY_RE.findall(_plain(text or ""))
    if legacy:
        return Verdict(Status(legacy[-1].upper()), None, "legacy")

    return Verdict(Status.CHANGES_REQUESTED, None, "none", parse_failed=True)
