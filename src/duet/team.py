"""관리자·작업자 분업 (DESIGN.md 29장).

관리자가 낸 작업 묶음(JSON)을 검증하고 줄 세우며, 파일 소유를 판단한다.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

MAX_PACKAGES = 12
NOTES_FILE = "IMPLEMENTATION_NOTES.md"
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,15}$")
_FORBIDDEN_TOP = {".git", ".duet"}

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "packages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "files": {"type": "array", "items": {"type": "string"}},
                    "goal": {"type": "string"},
                    "interfaces": {"type": "string"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "title", "files", "goal", "interfaces", "depends_on"],
                "additionalProperties": False,
            },
        },
        "shared": {"type": "string"},
    },
    "required": ["packages", "shared"],
    "additionalProperties": False,
}

OUTPUT_INSTRUCTION = """응답은 지정된 JSON 형식으로만 한다.
- packages: 작업 묶음 목록. id 는 P1, P2 … , title 은 한 줄, files 는 이 묶음이 소유하는 파일·폴더(작업 폴더 기준 상대 경로,
  폴더는 / 로 끝냄, 묶음끼리 겹치면 안 됨), goal 은 무엇을 만들지, interfaces 는 다른 묶음이 쓰는 함수·클래스·형식,
  depends_on 은 먼저 끝나야 하는 묶음 id 목록.
- shared: 모든 작업자가 지킬 공통 약속(이름 규칙, 공통 자료형, 테스트 방식). 없으면 빈 문자열."""


class PlanError(ValueError):
    pass


def _norm_path(p: Any) -> str:
    s = str(p or "").strip().replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    if not s or s.startswith("/") or re.match(r"^[A-Za-z]:", s):
        raise PlanError(f"상대 경로가 아닙니다: {p!r}")
    parts = PurePosixPath(s.rstrip("/")).parts
    if ".." in parts or (parts and parts[0] in _FORBIDDEN_TOP):
        raise PlanError(f"쓸 수 없는 경로입니다: {p!r}")
    return s


def _overlaps(a: str, b: str) -> bool:
    """두 소유 경로가 겹치는가 (같은 파일, 또는 한쪽이 다른 쪽 폴더 안)."""
    da, db = a.endswith("/"), b.endswith("/")
    if a == b:
        return True
    if da and b.startswith(a):
        return True
    if db and a.startswith(b):
        return True
    return False


def validate(data: Any) -> dict[str, Any]:
    """관리자의 JSON → {packages: [...], order: [id...], shared}. 틀리면 PlanError."""
    if not isinstance(data, dict) or not isinstance(data.get("packages"), list):
        raise PlanError("packages 목록이 없습니다")
    raw = data["packages"]
    if not 1 <= len(raw) <= MAX_PACKAGES:
        raise PlanError(f"묶음은 1~{MAX_PACKAGES}개여야 합니다: {len(raw)}개")
    packages = []
    seen: set[str] = set()
    for i, p in enumerate(raw, 1):
        if not isinstance(p, dict):
            raise PlanError(f"{i}번째 묶음이 객체가 아닙니다")
        pid = str(p.get("id") or "").strip()
        if not _ID_RE.match(pid):
            raise PlanError(f"{i}번째 묶음의 id 가 잘못되었습니다: {pid!r}")
        if pid in seen:
            raise PlanError(f"묶음 id 가 겹칩니다: {pid}")
        seen.add(pid)
        files = [_norm_path(f) for f in (p.get("files") or [])]
        if not files:
            raise PlanError(f"{pid}: files 가 비었습니다")
        deps = [str(d).strip() for d in (p.get("depends_on") or []) if str(d).strip()]
        packages.append({"id": pid, "title": str(p.get("title") or "").strip() or pid, "files": list(dict.fromkeys(files)),
                         "goal": str(p.get("goal") or "").strip(), "interfaces": str(p.get("interfaces") or "").strip(),
                         "depends_on": deps})
    owners: list[tuple[str, str]] = []
    for p in packages:
        for f in p["files"]:
            for other_id, g in owners:
                if other_id != p["id"] and _overlaps(f, g):
                    raise PlanError(f"파일 소유가 겹칩니다: {p['id']} 의 {f} ↔ {other_id} 의 {g}")
            owners.append((p["id"], f))
        for d in p["depends_on"]:
            if d not in seen:
                raise PlanError(f"{p['id']}: 없는 묶음에 의존합니다: {d}")
            if d == p["id"]:
                raise PlanError(f"{p['id']}: 자기 자신에 의존합니다")
    return {"packages": packages, "order": _topo(packages), "shared": str(data.get("shared") or "").strip()}


def _topo(packages: list[dict]) -> list[str]:
    """의존 순서. 같은 단계는 적힌 순서. 순환이면 PlanError."""
    done: list[str] = []
    pending = [p["id"] for p in packages]
    deps = {p["id"]: set(p["depends_on"]) for p in packages}
    while pending:
        ready = [pid for pid in pending if deps[pid] <= set(done)]
        if not ready:
            raise PlanError(f"묶음 의존이 순환합니다: {', '.join(pending)}")
        done.append(ready[0])
        pending.remove(ready[0])
    return done


def fallback_plan(reason: str) -> dict[str, Any]:
    """계획을 못 쓰면 묶음 하나(전체)를 첫 작업자가 맡는다 (소유 확인 없음)."""
    return {"packages": [{"id": "P1", "title": "전체 구현", "files": ["./"], "goal": "설계 문서 전체를 구현한다",
                          "interfaces": "", "depends_on": []}], "order": ["P1"], "shared": "", "fallback": reason}


def owns(pkg: dict, path: str) -> bool:
    path = path.replace("\\", "/").lstrip("./") if path.startswith("./") else path.replace("\\", "/")
    for f in pkg["files"]:
        if f in ("./", ".", "/"):
            return True
        if f.endswith("/"):
            if path.startswith(f) or path == f.rstrip("/"):
                return True
        elif path == f:
            return True
    return False


def owner_of(plan: dict, path: str) -> str | None:
    p = str(path or "").strip().strip("`")
    p = re.sub(r":\d+(?::\d+)?(?:-\d+)?$", "", p)          # a.py:12 같은 위치 표시
    if not p:
        return None
    for pkg in plan["packages"]:
        if owns(pkg, p):
            return pkg["id"]
    return None


def outside(pkg: dict, changed: list[str]) -> list[str]:
    """묶음 소유와 IMPLEMENTATION_NOTES.md 밖에서 바뀐 파일."""
    return [f for f in changed if f != NOTES_FILE and not owns(pkg, f)]


def package(plan: dict, pid: str) -> dict:
    return next(p for p in plan["packages"] if p["id"] == pid)


def format_files(pkg: dict) -> str:
    return "\n".join(f"- {f}" for f in pkg["files"])


def format_others(plan: dict, pid: str) -> str:
    rows = [f"- {p['id']} {p['title']} (파일: {', '.join(p['files'])})\n  {p['interfaces'] or '(인터페이스 없음)'}"
            for p in plan["packages"] if p["id"] != pid]
    return "\n".join(rows) or "(없음)"


def format_parts(plan: dict, parts: dict) -> str:
    rows = []
    for pid in plan["order"]:
        p = package(plan, pid)
        rec = parts.get(pid) or {}
        extra = f" — 되돌린 파일: {', '.join(rec['reverted'])}" if rec.get("reverted") else ""
        rows.append(f"- {pid} {p['title']} (담당 {rec.get('worker', '?')}, 파일: {', '.join(p['files'])}){extra}\n"
                    f"  목표: {p['goal'] or '-'}\n  인터페이스: {p['interfaces'] or '-'}")
    return "\n".join(rows)
