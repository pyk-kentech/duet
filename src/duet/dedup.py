"""재제기 확인 (DESIGN.md 26.2).

새로 붙은 막는 지적이 이미 닫힌 지적(해결·기각·중재 완화)을 다시 말한 것인지 작은 모델에게 묻고, 결과를 판정에 적용한다.
- 기각·완화된 지적의 재제기 → P3
- 해결된 지적의 재발 → 심각도 유지, "재발" 표시
- 같은 리뷰어가 지난 라운드에 낸 지적을 ID 없이 다시 쓴 것(이번에 목록에서 빠져 해결로 처리될 참) → 원래 ID 로 합침
"""

from __future__ import annotations

from typing import Any

DEDUP_ROLE = "dedup"
BLOCKING = ("P1", "P2")
MAX_CLOSED = 15

DEDUP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "new_id": {"type": "string"},
                    "old_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["new_id", "old_id", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["matches"],
    "additionalProperties": False,
}

OUTPUT_INSTRUCTION = """응답은 지정된 JSON 형식으로만 한다.
- matches: 새 지적 중 이전 지적과 같은 문제인 것만. new_id 는 새 지적의 ID, old_id 는 이전 지적의 ID, reason 은 한 문장.
  같은 문제가 없으면 빈 배열."""


def closed_issues(state) -> list[dict]:
    """닫힌 지적: 해결·기각된 것, 그리고 중재에서 완화돼 P3 로 열려 있는 것. 최근 것부터 최대 MAX_CLOSED 개."""
    items = [x for x in state.issues
             if x.get("status") in ("resolved", "rejected")
             or (x.get("status") == "open" and str(x.get("note") or "").startswith("중재: 완화"))]
    items.sort(key=lambda x: (x.get("closed_round") or x.get("round") or 0), reverse=True)
    return items[:MAX_CLOSED]


def pending_issues(state, role: str, findings: list[dict]) -> list[dict]:
    """그 리뷰어의 열린 지적 중 이번 리뷰가 ID 로 다시 적지 않은 것. 원장 갱신 때 해결로 처리될 참이다."""
    listed = {f.get("id") for f in findings}
    return [{**x, "status": "pending"} for x in state.issues
            if x.get("role") == role and x.get("status") == "open" and x["id"] not in listed
            and not str(x.get("note") or "").startswith("중재: 완화")]


def how_closed(x: dict) -> str:
    if x.get("status") == "pending":
        return "지난 라운드 지적, 이번 리뷰에서 ID 로 다시 적지 않음"
    if x.get("status") == "resolved":
        return f"{x.get('closed_round')}라운드에 해결됨"
    if x.get("status") == "rejected":
        return "중재에서 기각됨" + _reason(x)
    return "중재에서 완화됨(P3)" + _reason(x)


def _reason(x: dict) -> str:
    note = str(x.get("note") or "")
    _, _, reason = note.partition(" — ")
    return f": {reason.strip()[:120]}" if reason.strip() else ""


def format_closed(items: list[dict]) -> str:
    return "\n".join(f"- {x['id']} [{x['severity']}] {x['title']}" + (f" — `{x['file']}`" if x.get("file") else "")
                     + f" ({how_closed(x)})" for x in items) or "(없음)"


def closed_block(state, for_fix: bool = False) -> str:
    """리뷰·수정 프롬프트에 붙일 닫힌 지적 목록 (DESIGN.md 26.1). 없으면 빈 문자열."""
    items = closed_issues(state)
    if not items:
        return ""
    head = ("[이미 닫힌 지적] 아래 지적을 고친 코드를 되돌리지 마라. 다른 지적을 고치다 이 결함이 되살아나지 않게 해라."
            if for_fix else
            "[이미 닫힌 지적] 아래는 이미 해결됐거나 중재에서 정리된 지적이다. 회귀(해결된 결함이 되살아남)가 아니면 "
            "다시 내지 마라. 회귀면 그 ID 를 적어라.")
    return head + "\n" + format_closed(items)


def new_blocking(findings: list[dict]) -> list[dict]:
    return [f for f in findings if f.get("new") and f.get("severity") in BLOCKING]


def format_new(findings: list[dict]) -> str:
    lines = []
    for f in findings:
        detail = " ".join(str(f.get("detail") or "").split())[:300]
        lines.append(f"- {f['id']} [{f['severity']}] {f.get('title', '')}"
                     + (f" — `{f['file']}`" if f.get("file") else "") + (f"\n  {detail}" if detail else ""))
    return "\n".join(lines)


def normalize(data: Any, new_ids: set[str], closed_ids: set[str]) -> dict[str, dict] | None:
    """확인 JSON → {new_id: {old_id, reason}}. 목록 밖 ID 는 버린다. 형식이 틀리면 None."""
    if not isinstance(data, dict) or not isinstance(data.get("matches"), list):
        return None
    out: dict[str, dict] = {}
    for m in data["matches"]:
        if not isinstance(m, dict):
            continue
        nid, oid = str(m.get("new_id") or "").strip(), str(m.get("old_id") or "").strip()
        if nid in new_ids and oid in closed_ids and nid not in out:
            out[nid] = {"old_id": oid, "reason": str(m.get("reason") or "").strip()}
    return out


def apply(findings: list[dict], matches: dict[str, dict], closed_by_id: dict[str, dict]) -> dict[str, int]:
    """판정 지적에 확인 결과를 적용한다(제자리 수정). 결과: {"repeat": 낮춘 수, "recurred": 재발 표시 수, "same": 합친 수}"""
    counts = {"repeat": 0, "recurred": 0, "same": 0}
    taken = {f.get("id") for f in findings}
    for f in findings:
        m = matches.get(f.get("id"))
        if m is None:
            continue
        old = closed_by_id[m["old_id"]]
        if old.get("status") == "pending":
            if m["old_id"] in taken:
                continue                  # 그 ID 를 이미 다른 지적이 쓰고 있다
            taken.add(m["old_id"])
            f["note"] = (f"{f['note']}; " if f.get("note") else "") + f"{f['id']} → {m['old_id']} 와 같은 지적"
            f["id"], f["new"] = m["old_id"], False
            counts["same"] += 1
            continue
        f["repeat_of"] = m["old_id"]
        if old.get("status") == "resolved":
            f["note"] = (f"{f['note']}; " if f.get("note") else "") + f"{m['old_id']} 재발(회귀 가능성)"
            counts["recurred"] += 1
        elif f.get("severity") in BLOCKING:
            f["note"] = f"원래 {f['severity']}: {m['old_id']} 재제기 — {how_closed(old)}"
            f["severity"] = "P3"
            counts["repeat"] += 1
    return counts
