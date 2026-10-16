"""지적 원장과 판정 관문 (DESIGN.md 22장).

JSON 판정(review_json.py)의 지적을 duet 가 기계적으로 보정한다.
- 원장: 리뷰어(역할)별 지적에 안정 ID(I1, I2, …)를 붙이고 라운드를 넘어 추적한다.
- 근거 관문: P1·P2 인데 evidence 가 비면 P3.
- 범위 관문(2라운드부터): 새 P2 지적의 file 이 지난 리뷰 이후 바뀐 파일이 아니면 P3. P1 은 그대로.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from duet.review_json import SEVERITIES

BLOCKING = ("P1", "P2")
_ID_RE = re.compile(r"^I(\d+)$")


@dataclass
class GateResult:
    data: dict[str, Any]                                   # 보정한 판정 (렌더·원장 갱신용)
    downgraded: dict[str, int] = field(default_factory=lambda: {"evidence": 0, "scope": 0})


def open_issues(state, role: str) -> list[dict]:
    return [x for x in state.issues if x.get("role") == role and x.get("status") == "open"]


def format_open(issues: Iterable[dict]) -> str:
    lines = [f"- {x['id']} [{x['severity']}] {x['title']}" + (f" — `{x['file']}`" if x.get("file") else "")
             for x in issues]
    return "\n".join(lines) or "(없음)"


def next_number(state) -> int:
    nums = [int(m.group(1)) for x in state.issues if (m := _ID_RE.match(str(x.get("id", ""))))]
    return max(nums, default=0) + 1


def _norm(path: str) -> str:
    p = str(path or "").strip().strip("`").strip()
    p = re.sub(r":\d+(?::\d+)?(?:-\d+)?$", "", p)        # a.py:12, a.py:12:3, a.py:3-9
    while p.startswith("./"):
        p = p[2:]
    return p


def touches(file: str, changed: set[str]) -> bool:
    f = _norm(file)
    if not f:
        return False
    for c in changed:
        if f == c or c.endswith("/" + f) or f.endswith("/" + c):
            return True
    return False


def apply_gates(data: dict[str, Any], *, round_: int, open_ids: set[str], changed_files: set[str] | None,
                first_number: int, only_ids: set[str] | None = None) -> GateResult:
    """판정을 보정해 새 dict 로 돌려준다. 원장은 바꾸지 않는다(update_ledger 가 한다).

    only_ids: 중재 뒤 마지막 라운드. 이 ID 밖의 지적은 모두 P3 (DESIGN.md 23.4).
    """
    out = dict(data)
    res = GateResult(out)
    n = first_number
    findings = []
    for f in data.get("findings") or []:
        if not isinstance(f, dict) or f.get("severity") not in SEVERITIES:
            continue
        fid = str(f.get("id") or "").strip()
        existing = fid in open_ids
        if not existing:
            fid = f"I{n}"
            n += 1
        sev, note = f["severity"], None
        if only_ids is not None and fid not in only_ids and sev in BLOCKING:
            sev, note = "P3", "중재 후 막는 기준 밖"
            res.downgraded["arbiter"] = res.downgraded.get("arbiter", 0) + 1
        elif sev in BLOCKING and not str(f.get("evidence") or "").strip():
            sev, note = "P3", "근거 없음"
            res.downgraded["evidence"] += 1
        elif (sev == "P2" and not existing and round_ >= 2 and changed_files is not None
              and not touches(str(f.get("file") or ""), changed_files)):
            sev, note = "P3", "이번 변경과 무관한 새 지적"
            res.downgraded["scope"] += 1
        g = {**f, "id": fid, "severity": sev, "new": not existing}
        if note:
            g["note"] = f"원래 {f['severity']}: {note}"
        findings.append(g)
    out["findings"] = findings
    return res


def update_ledger(state, role: str, round_: int, findings: list[dict]) -> None:
    """보정한 지적으로 원장을 갱신한다. 이번에 다시 적히지 않은 그 리뷰어의 열린 지적은 해결로 본다."""
    seen = set()
    by_id = {x["id"]: x for x in state.issues}
    for f in findings:
        fid = f["id"]
        seen.add(fid)
        item = by_id.get(fid)
        if item is not None and item.get("role") == role:
            item.update(severity=f["severity"], title=str(f.get("title") or item["title"]),
                        file=str(f.get("file") or item.get("file") or ""), status="open",
                        note=f.get("note") or "")
        else:
            state.issues.append({"id": fid, "role": role, "round": round_, "severity": f["severity"],
                                 "title": str(f.get("title") or ""), "file": str(f.get("file") or ""),
                                 "status": "open", "closed_round": None, "note": f.get("note") or ""})
    for x in state.issues:
        if x.get("role") == role and x.get("status") == "open" and x["id"] not in seen:
            x["status"] = "resolved"
            x["closed_round"] = round_
