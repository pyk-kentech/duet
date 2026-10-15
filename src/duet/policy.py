"""승인 판단과 반려 핑퐁(수렴 실패) 감지."""

from __future__ import annotations

from dataclasses import dataclass, field

from duet.verdict import Status, Verdict

SEVERITY_ORDER = ("P1", "P2", "P3")


def blocking_count(v: Verdict, block_severity: str) -> int | None:
    """반려 기준에 걸리는 지적 수. 심각도가 없으면 must_fix, 그것도 없으면 None."""
    if v.severity:
        upto = SEVERITY_ORDER[: SEVERITY_ORDER.index(block_severity) + 1]
        return sum(v.severity.get(k, 0) for k in upto)
    return v.must_fix


@dataclass
class Decision:
    approved: bool
    blocking: int | None
    reasons: list[str] = field(default_factory=list)

    def describe(self) -> str:
        head = "APPROVED" if self.approved else "CHANGES_REQUESTED"
        return head + (f" ({'; '.join(self.reasons)})" if self.reasons else "")


def decide(v: Verdict, *, block_severity: str, tests_block: bool, require_tests_pass: bool) -> Decision:
    blocking = None if v.parse_failed else blocking_count(v, block_severity)
    reasons: list[str] = []
    if v.parse_failed:
        approved = False
        reasons.append("판정 블록 없음 → 반려로 간주")
    elif v.severity is not None:
        approved = blocking == 0
        if approved and v.status is not Status.APPROVED:
            reasons.append(f"{block_severity} 이상 지적이 없어 승인 (리뷰어 판정: {v.status.value})")
        if not approved and v.status is Status.APPROVED:
            reasons.append(f"APPROVED 인데 {block_severity} 이상 지적 {blocking}건 → 반려")
        if v.severity:
            reasons.append(" ".join(f"{k}={v.severity.get(k, 0)}" for k in SEVERITY_ORDER))
    else:
        approved = v.approved
        if v.contradiction:
            reasons.append("APPROVED 인데 must_fix>0 → 반려")
        if v.must_fix is not None:
            reasons.append(f"must_fix={v.must_fix}")
    if approved and tests_block and require_tests_pass:
        approved = False
        reasons.append("테스트 실패로 승인 보류")
    return Decision(approved, blocking, reasons)


def stalled(history: list[int | None], rounds: int) -> bool:
    """막는 지적 수가 최근 `rounds` 라운드 연속으로 그 전까지의 최저치보다 낮아지지 않았는가."""
    if rounds <= 0:
        return False
    counts = [c for c in history if c is not None]
    if len(counts) <= rounds:
        return False
    best_before = min(counts[: -rounds])
    return all(c >= best_before for c in counts[-rounds:])
