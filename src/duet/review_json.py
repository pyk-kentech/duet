"""JSON 판정 (DESIGN.md 21.2).

리뷰 호출에 출력 스키마를 붙이고, 받은 JSON 을 기존 마크다운 리뷰 형식으로 바꾼다.
그래서 판정 파싱(verdict.py)·수정 프롬프트·재현 테스트·UI 는 그대로 쓴다.
스키마는 엄격 모드(모든 필드 필수, 추가 필드 없음)와 호환되게 만든다. 엄격 모드가 받지 않을 수 있는 키워드
(maxItems 등)는 쓰지 않고, 개수 제한은 안내 문구와 변환 때 자르기로 지킨다.
"""

from __future__ import annotations

import re
from typing import Any

SEVERITIES = ("P1", "P2", "P3")
BASES = ("requirement", "correctness", "security", "preference")   # 지적의 근거 종류 (DESIGN.md 25.2)
MAX_FINDINGS = 12
MAX_REPROS = 5

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["APPROVED", "CHANGES_REQUESTED"]},
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "severity": {"type": "string", "enum": list(SEVERITIES)},
                    "new": {"type": "boolean"},
                    "title": {"type": "string"},
                    "file": {"type": "string"},
                    "detail": {"type": "string"},
                    "evidence": {"type": "string"},
                    "basis": {"type": "string", "enum": list(BASES)},
                    "requirement": {"type": "string"},
                },
                "required": ["id", "severity", "new", "title", "file", "detail", "evidence", "basis", "requirement"],
                "additionalProperties": False,
            },
        },
        "repro": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["status", "summary", "findings", "repro"],
    "additionalProperties": False,
}

OUTPUT_INSTRUCTION_JSON = """응답은 지정된 JSON 형식으로만 한다.
- findings: 지적마다 하나. id 는 [열린 지적 목록]에 있는 지적이 아직 해결되지 않았으면 그 ID(예: I3), 새 지적이면 빈 문자열.
  severity 는 위 기준의 P1/P2/P3, new 는 이번에 처음 찾은 지적이면 true, title 은 한 줄 요약,
  file 은 관련 파일 경로(없으면 빈 문자열), detail 은 무엇이 왜 문제이고 어떻게 고칠지, evidence 는 근거(실패하는 입력,
  코드 위치, 실행 결과 등. 없으면 빈 문자열). 최대 12개, 중요한 것부터.
  basis 는 근거 종류: requirement(과제·설계 문서의 요구를 어김), correctness(요구와 무관하게 틀린 동작: 크래시·잘못된 결과·
  데이터 손실), security(보안), preference(취향·스타일·과한 방어·적히지 않은 호환성). requirement 는 basis 가
  requirement 일 때 과제나 설계 문서의 해당 문장을 고치지 말고 그대로 인용, 아니면 빈 문자열.
- status: P1·P2 지적이 없으면 APPROVED, 있으면 CHANGES_REQUESTED.{gate_hint}
- summary: 전체 평가 두세 문장.
- repro: {repro_hint}"""

REPRO_HINT_ON = ("P1·P2 중 코드로 재현할 수 있는 것은 지금 코드에서 실패하는 테스트를 넣어라: path 는 프로젝트의 테스트 폴더 안 "
                 "새 파일(예: tests/test_repro_짧은이름.py), content 는 테스트 코드. duet 가 저장해 실제로 실패하는지 돌려 본다. "
                 "최대 5개. 없으면 빈 배열.")
REPRO_HINT_OFF = "항상 빈 배열."

OUTPUT_INSTRUCTION_TEXT = """{repro_instruction}

다음 순서로 답해라:
## 반드시 고칠 것 (P1·P2)
## 고치면 좋은 것 (P3)
## 잘한 점

응답 마지막에 아래 블록을 정확히 이 형식으로 써라. 숫자는 심각도별 지적 개수다.
'반드시 고칠 것'이 비어 있으면 APPROVED다.

<verdict>
status: APPROVED 또는 CHANGES_REQUESTED
must_fix: 숫자
p1: 숫자
p2: 숫자
p3: 숫자
</verdict>"""


GATE_HINT = ("\n- duet 가 판정을 기계적으로 보정한다: P1·P2 인데 evidence 가 비어 있으면 P3 로 낮추고, 2라운드부터는 "
             "지난 리뷰 이후 바뀌지 않은 파일에 대한 새 P2 지적도 P3 로 낮춘다(P1 은 그대로). 막아야 할 지적이면 근거를 적어라.")


SPEC_HINT = ("\n- 또 basis 가 preference 인 P1·P2 는 P3 로, basis 가 requirement 인 P2 는 인용한 문장을 과제·설계 문서에서 "
             "찾을 수 없으면 P3 로 낮춘다. 요구를 말로 풀어 쓰지 말고 원문을 인용해라.")


def output_instruction(json_mode: bool, repro_tests: bool, repro_instruction: str, gates: bool = False,
                       spec: bool = False) -> str:
    if json_mode:
        return (OUTPUT_INSTRUCTION_JSON.replace("{repro_hint}", REPRO_HINT_ON if repro_tests else REPRO_HINT_OFF)
                .replace("{gate_hint}", (GATE_HINT if gates else "") + (SPEC_HINT if gates and spec else "")))
    return OUTPUT_INSTRUCTION_TEXT.replace("{repro_instruction}", repro_instruction).strip()


NEW_TAG_RE = re.compile(r"^\s*(?:\[(?:새|new|NEW)\]\s*)+")


def clean_title(title: Any) -> str:
    """모델이 제목에도 붙이는 [새] 를 뗀다 (렌더·지적 원장 공용)."""
    return NEW_TAG_RE.sub("", str(title or "")).strip()


def _finding(f: dict[str, Any]) -> str:
    tag = f"[{f.get('severity', 'P3')}]" + ("[새]" if f.get("new") else "") + (f"[{f['id']}]" if f.get("id") else "")
    title = clean_title(f.get("title"))   # 모델이 제목에도 [새] 를 붙임
    head = f"- {tag} {title}"
    if str(f.get("file") or "").strip():
        head += f" — `{str(f['file']).strip()}`"
    if f.get("note"):
        head += f" ({f['note']})"
    lines = [head]
    detail = str(f.get("detail") or "").strip()
    if detail:
        lines += ["  " + ln for ln in detail.splitlines()]
    evidence = str(f.get("evidence") or "").strip()
    if evidence:
        lines.append("  근거: " + " ".join(evidence.splitlines()))
    req = str(f.get("requirement") or "").strip()
    if f.get("basis") == "requirement" and req:
        lines.append("  요구: «" + " ".join(req.splitlines()) + "»")
    return "\n".join(lines)


def render_review(data: Any) -> str | None:
    """구조화 판정 → 기존 마크다운 리뷰. 형식이 맞지 않으면 None (호출한 쪽이 본문을 그대로 쓴다)."""
    if not isinstance(data, dict) or data.get("status") not in ("APPROVED", "CHANGES_REQUESTED"):
        return None
    findings = data.get("findings")
    if not isinstance(findings, list) or not all(isinstance(f, dict) for f in findings):
        return None
    findings = [f for f in findings if f.get("severity") in SEVERITIES][:MAX_FINDINGS]
    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITIES}
    must = [f for f in findings if f["severity"] in ("P1", "P2")]
    nice = [f for f in findings if f["severity"] == "P3"]
    parts = ["## 반드시 고칠 것 (P1·P2)", "\n".join(_finding(f) for f in must) or "(없음)", "",
             "## 고치면 좋은 것 (P3)", "\n".join(_finding(f) for f in nice) or "(없음)", "",
             "## 요약", str(data.get("summary") or "").strip() or "(없음)", ""]
    repros = data.get("repro") if isinstance(data.get("repro"), list) else []
    for r in repros[:MAX_REPROS]:
        if isinstance(r, dict) and str(r.get("path") or "").strip() and str(r.get("content") or "").strip():
            parts += [f'<repro path="{str(r["path"]).strip()}">', str(r["content"]).rstrip(), "</repro>", ""]
    parts += ["<verdict>", f"status: {data['status']}", f"must_fix: {len(must)}",
              f"p1: {counts['P1']}", f"p2: {counts['P2']}", f"p3: {counts['P3']}", "</verdict>"]
    return "\n".join(parts) + "\n"
