"""되돌림 감지 (DESIGN.md 26.3).

지난 리뷰 이후의 변경이 이전 시점 k 의 코드를 되살리고, 그 사이에 같은 파일의 지적이 해결됐으면 경고한다.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from duet.gates import touches
from duet.workspace import GitError, Workspace

MIN_LINE = 4
RATIO = 0.5
_HUNK_RE = re.compile(r"^@@ ")


@dataclass
class Revert:
    file: str
    point: int            # 되살린 코드의 시점: 0 = 기준 커밋, k = k라운드 리뷰 시점
    lines: int            # 되살린 줄 수
    issues: list[str]     # 그 사이 해결됐던 지적 ID

    def to_dict(self) -> dict:
        return asdict(self)


def _sig(line: str) -> str | None:
    s = line.strip()
    return s if len(s) >= MIN_LINE else None


def _changes(ws: Workspace, frm: str, path: str) -> tuple[list[str], list[str]]:
    out = ws.git("diff", "-U0", "--no-color", frm, "HEAD", "--", path)
    added, removed = [], []
    for ln in out.splitlines():
        if ln.startswith(("+++", "---")) or _HUNK_RE.match(ln):
            continue
        if ln.startswith("+") and (s := _sig(ln[1:])):
            added.append(s)
        elif ln.startswith("-") and (s := _sig(ln[1:])):
            removed.append(s)
    return added, removed


def _lines_at(ws: Workspace, rev: str, path: str) -> set[str] | None:
    try:
        text = ws.git("show", f"{rev}:{path}")
    except GitError:
        return None
    return {s for ln in text.splitlines() if (s := _sig(ln))}


def find_reverts(ws: Workspace, prev: str, points: list[tuple[int, str]], issues: list[dict],
                 exclude: tuple[str, ...] = ()) -> list[Revert]:
    """prev → HEAD 변경 중 되돌림. points: [(시점 번호, 커밋)] (오래된 것부터, prev 제외). issues: 원장."""
    try:
        files = [f for f in ws.git("diff", "--name-only", prev, "HEAD").splitlines() if f.strip()]
    except GitError:
        return []
    found = []
    for path in files:
        if path in exclude:
            continue
        crossed_any = [x for x in issues if x.get("status") == "resolved" and touches(str(x.get("file") or ""), {path})]
        if not crossed_any:
            continue
        try:
            added, removed = _changes(ws, prev, path)
        except GitError:
            continue
        if not added or not removed:
            continue
        for k, commit in reversed(points):          # 가장 최근 시점부터
            then = _lines_at(ws, commit, path)
            if not then:
                continue
            restored = sum(1 for a in added if a in then)
            back = restored / len(added)
            gone = sum(1 for r in removed if r not in then) / len(removed)
            if not restored or back < RATIO or gone < RATIO:
                continue
            crossed = [x["id"] for x in crossed_any if int(x.get("round") or 0) <= k < int(x.get("closed_round") or 0)]
            if crossed:
                found.append(Revert(path, k, restored, crossed))
            break
    return found


def format_reverts(reverts: list[dict]) -> str:
    if not reverts:
        return ""
    lines = ["[되돌림 경고] duet 가 지난 리뷰 이후의 변경에서 예전 코드를 되살린 흔적을 찾았다:"]
    for r in reverts:
        when = "기준 커밋" if r["point"] == 0 else f"{r['point']}라운드 리뷰 시점"
        lines.append(f"- `{r['file']}`: {when}의 코드 {r['lines']}줄을 되살림. 그 뒤 해결됐던 지적: {', '.join(r['issues'])}")
    lines.append("그 지적의 결함이 되살아났는지 확인해라. 되살아났으면 그 ID 로 다시 지적해라.")
    return "\n".join(lines)
