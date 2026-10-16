"""분쟁 중재자 (DESIGN.md 23장).

리뷰가 수렴하지 않거나 상한에 닿았을 때 한 번, 지적 원장(gates.py)의 열린 지적을
유지(uphold)·완화(downgrade → P3)·기각(reject) 중 하나로 정한다.
"""

from __future__ import annotations

from typing import Any

from duet.policy import SEVERITY_ORDER

DECISIONS = ("uphold", "downgrade", "reject")
DECISION_KO = {"uphold": "유지", "downgrade": "완화(P3)", "reject": "기각"}

ARBITER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "decision": {"type": "string", "enum": list(DECISIONS)},
                    "reason": {"type": "string"},
                },
                "required": ["id", "decision", "reason"],
                "additionalProperties": False,
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["decisions", "summary"],
    "additionalProperties": False,
}

OUTPUT_INSTRUCTION = """응답은 지정된 JSON 형식으로만 한다.
- decisions: 위 목록의 지적마다 하나. id 는 그 지적의 ID(예: I3), decision 은 uphold / downgrade / reject, reason 은 한두 문장.
- summary: 전체 판단을 두세 문장으로. 구현자가 마지막으로 무엇을 고치면 되는지 분명히 적어라."""


BASIS_KO = {"requirement": "요구 위반", "correctness": "정확성", "security": "보안", "preference": "취향"}


def _basis(x: dict) -> str:
    """요구 근거 (DESIGN.md 25.2). 기록이 없으면(예전 실행) 빈 문자열."""
    b = x.get("basis")
    if not b:
        return ""
    req = str(x.get("requirement") or "").strip()
    if b == "requirement" and req:
        return f" — 요구: «{req[:160]}»"
    return f" — 근거 종류: {BASIS_KO.get(b, b)}"


def format_issues(items: list[dict]) -> str:
    return "\n".join(
        f"- {x['id']} [{x['severity']}] {x['title']}" + (f" — `{x['file']}`" if x.get("file") else "")
        + f" (리뷰어 {x['role']}, {x['round']}라운드부터 열림)" + _basis(x) for x in items) or "(없음)"


def normalize(data: Any, items: list[dict]) -> dict[str, dict] | None:
    """중재 JSON → {id: {decision, reason}}. 목록에 없는 ID 는 버리고, 빠진 지적은 유지로 본다."""
    if not isinstance(data, dict) or not isinstance(data.get("decisions"), list):
        return None
    ids = {x["id"] for x in items}
    out = {i: {"decision": "uphold", "reason": "(중재자가 결정하지 않음 → 유지)"} for i in ids}
    for d in data["decisions"]:
        if isinstance(d, dict) and d.get("id") in ids and d.get("decision") in DECISIONS:
            out[d["id"]] = {"decision": d["decision"], "reason": str(d.get("reason") or "").strip()}
    return out


def render(decisions: dict[str, dict], items: list[dict], summary: str) -> str:
    lines = ["## 중재 결과"]
    for x in items:
        d = decisions.get(x["id"], {"decision": "uphold", "reason": ""})
        lines.append(f"- {x['id']} [{x['severity']}] {x['title']} → **{DECISION_KO[d['decision']]}**"
                     + (f": {d['reason']}" if d["reason"] else ""))
    lines += ["", "## 요약", summary.strip() or "(없음)", ""]
    return "\n".join(lines)


def apply(state, decisions: dict[str, dict], round_: int) -> dict[str, list[str]]:
    """원장에 결정을 적용한다. 결과: {uphold: [...], downgrade: [...], reject: [...]}"""
    result: dict[str, list[str]] = {k: [] for k in DECISIONS}
    for x in state.issues:
        d = decisions.get(x["id"])
        if d is None or x.get("status") != "open":
            continue
        result[d["decision"]].append(x["id"])
        if d["decision"] == "downgrade":
            x["severity"] = "P3"
            x["note"] = f"중재: 완화 — {d['reason']}"
        elif d["decision"] == "reject":
            x["status"] = "rejected"
            x["closed_round"] = round_
            x["note"] = f"중재: 기각 — {d['reason']}"
    return result


def blocking_ids(state, block_severity: str) -> list[str]:
    upto = SEVERITY_ORDER[: SEVERITY_ORDER.index(block_severity) + 1]
    return [x["id"] for x in state.issues if x.get("status") == "open" and x.get("severity") in upto]
