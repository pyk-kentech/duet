"""테스트 변조 감지 (DESIGN.md 24.1).

구현 커밋 뒤, 리뷰 전에 테스트 쪽 변경을 비교 기준(1라운드: 기준 커밋, 이후: 지난 리뷰 시점)과 견준다.
막지는 않고 리뷰어·중재자에게 경고만 붙인다. 정당한 변경(틀린 재현 테스트 수정, 리팩터링)과 구별할 수 없다.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Iterable

from duet.workspace import GitError, Workspace

CODE_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs", ".rb", ".java", ".kt"}
TEST_DIRS = {"tests", "test", "__tests__", "spec"}
CONFIG_FILES = {"pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml", "package.json", "duet.toml", "conftest.py"}

TEST_RE = re.compile(
    r"^\s*(?:async\s+)?def\s+test\w*\s*\(|^\s*func\s+Test\w*\s*\(|(?<![\w.])(?:it|test)\s*\(\s*['\"`]",
    re.MULTILINE)
ASSERT_RE = re.compile(
    r"^\s*assert\b|\bself\.assert\w+\s*\(|(?<![\w.])expect\s*\(|\bt\.(?:Error|Errorf|Fatal|Fatalf)\s*\("
    r"|\bassert(?:_\w+)?!\s*\(|\bpytest\.raises\s*\(",
    re.MULTILINE)
SKIP_RE = re.compile(
    r"\bpytest\.mark\.(?:skip|skipif|xfail)\b|\bpytest\.(?:skip|xfail)\s*\(|\bunittest\.skip|^\s*@skip\b"
    r"|\b(?:it|test|describe)\.skip\s*\(|(?<![\w.])x(?:it|describe)\s*\(|\bt\.Skip(?:f|Now)?\s*\(|#\[ignore\]",
    re.MULTILINE)
# 기존 설정 파일에서 바뀌면 경고할 줄
CONFIG_KEY_RE = {
    "package.json": re.compile(r'"test"\s*:'),
    "duet.toml": re.compile(r"^\s*test_command\b"),
}
PYTEST_KEY_RE = re.compile(r"addopts|testpaths|deselect|--ignore|\bignore\s*=|norecursedirs|collect_ignore"
                           r"|python_files|python_functions|pytest_collection_modifyitems|(?:^|\s)-k\s")
# 새로 생긴 설정 파일에서도 경고할 줄 (테스트를 빼는 설정)
EXCLUDE_KEY_RE = re.compile(r"deselect|--ignore|collect_ignore|pytest_collection_modifyitems|(?:^|\s)-k\s")

KIND_KO = {
    "deleted": "테스트 파일 삭제",
    "fewer_tests": "테스트 수 감소",
    "fewer_asserts": "단언 수 감소",
    "skip_added": "건너뛰기 추가",
    "config": "테스트 설정 변경",
    "repro_changed": "리뷰어 재현 테스트 변경",
}


@dataclass
class Signal:
    kind: str
    file: str
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


def is_test_file(path: str) -> bool:
    p = PurePosixPath(path)
    name = p.name
    if name == "conftest.py":
        return True
    if p.suffix not in CODE_EXTS:
        return False
    if any(part in TEST_DIRS for part in p.parts[:-1]):
        return True
    stem = name[: -len(p.suffix)]
    return (stem.startswith("test_") or stem.endswith("_test") or stem.endswith(".test")
            or stem.endswith(".spec"))


def _show(ws: Workspace, rev: str, path: str) -> str | None:
    try:
        return ws.git("show", f"{rev}:{path}")
    except GitError:
        return None


def _name_status(ws: Workspace, frm: str, to: str) -> list[tuple[str, str, str]]:
    """(상태, 예전 경로, 지금 경로). 이름 바꾸기는 R."""
    parts = ws.git("diff", "--name-status", "-z", "-M", frm, to).split("\0")
    rows = []
    i = 0
    while i < len(parts) and parts[i]:
        status = parts[i][0]
        if status in "RC":
            rows.append((status, parts[i + 1], parts[i + 2]))
            i += 3
        else:
            rows.append((status, parts[i + 1], parts[i + 1]))
            i += 2
    return rows


def _changed_lines(old: str, new: str) -> list[str]:
    """한쪽에만 있는 줄 (순서 무시, 설정 비교용)."""
    a, b = old.splitlines(), new.splitlines()
    sa, sb = set(a), set(b)
    return [x for x in a if x not in sb] + [x for x in b if x not in sa]


def _count(rx: re.Pattern[str], text: str) -> int:
    return len(rx.findall(text))


def _compare_test(path: str, old: str, new: str) -> list[Signal]:
    out = []
    t0, t1 = _count(TEST_RE, old), _count(TEST_RE, new)
    if t1 < t0:
        out.append(Signal("fewer_tests", path, f"테스트 {t0} → {t1}개"))
    a0, a1 = _count(ASSERT_RE, old), _count(ASSERT_RE, new)
    if a1 < a0:
        out.append(Signal("fewer_asserts", path, f"단언 {a0} → {a1}개"))
    s0, s1 = _count(SKIP_RE, old), _count(SKIP_RE, new)
    if s1 > s0:
        out.append(Signal("skip_added", path, f"skip/xfail {s0} → {s1}개"))
    return out


def _config_signal(path: str, old: str | None, new: str | None) -> Signal | None:
    name = PurePosixPath(path).name
    rx = CONFIG_KEY_RE.get(name, PYTEST_KEY_RE)
    if old is None:                       # 새 파일: 테스트를 빼는 설정만
        rx = EXCLUDE_KEY_RE if name not in CONFIG_KEY_RE else None
        lines = (new or "").splitlines()
    else:
        lines = _changed_lines(old, new or "")
    if rx is None:
        return None
    hits = [ln.strip() for ln in lines if rx.search(ln)]
    if not hits:
        return None
    shown = "; ".join(h[:80] for h in hits[:3]) + (" ..." if len(hits) > 3 else "")
    return Signal("config", path, ("삭제됨: " if new is None else "") + shown)


def scan(ws: Workspace, frm: str, to: str = "HEAD", repro_files: Iterable[tuple[str, str]] = ()) -> list[Signal]:
    """frm → to 사이 테스트 쪽 변경의 경고 신호.

    repro_files: (경로, 저장한 커밋) — 리뷰어 재현 테스트. frm 에 있으면 frm 의 내용, 없으면 저장 커밋의 내용과 견준다.
    """
    signals: list[Signal] = []
    repro = dict(repro_files)
    try:
        rows = _name_status(ws, frm, to)
    except GitError:
        return signals
    for status, old_path, new_path in rows:
        if old_path in repro or new_path in repro:
            continue                      # 아래에서 따로 본다
        name = PurePosixPath(new_path).name
        if name in CONFIG_FILES:
            old = None if status == "A" else _show(ws, frm, old_path)
            new = None if status == "D" else _show(ws, to, new_path)
            sig = _config_signal(new_path, old, new)
            if sig:
                signals.append(sig)
            if name != "conftest.py":
                continue
        if status == "A" or not (is_test_file(old_path) or is_test_file(new_path)):
            continue
        if status == "D":
            if is_test_file(old_path) and name != "conftest.py":
                n = _count(TEST_RE, _show(ws, frm, old_path) or "")
                signals.append(Signal("deleted", old_path, f"테스트 {n}개가 든 파일" if n else "파일 삭제"))
            continue
        old, new = _show(ws, frm, old_path), _show(ws, to, new_path)
        if old is None or new is None:
            continue
        label = new_path if old_path == new_path else f"{old_path} → {new_path}"
        signals.extend(_compare_test(label, old, new))
    for path, commit in repro.items():
        before = _show(ws, frm, path)
        if before is None:
            before = _show(ws, commit, path) if commit else None
        if before is None:
            continue
        after = _show(ws, to, path)
        if after is None:
            signals.append(Signal("repro_changed", path, "삭제됨"))
        elif after != before:
            detail = ", ".join(s.detail for s in _compare_test(path, before, after)) or "내용 바뀜"
            signals.append(Signal("repro_changed", path, detail))
    return signals


def repro_files(repros: dict[str, dict]) -> list[tuple[str, str]]:
    """state.repros → (경로, 저장 커밋)."""
    out: dict[str, str] = {}
    for rec in repros.values():
        for f in rec.get("files") or []:
            out[f] = rec.get("commit") or ""
    return list(out.items())


def format_signals(signals: list[dict], since: str) -> str:
    if not signals:
        return ""
    lines = [f"[테스트 변경 경고] duet 가 {since} 테스트 쪽 변경을 감지했다:"]
    for s in signals:
        lines.append(f"- {KIND_KO.get(s['kind'], s['kind'])}: `{s['file']}` ({s['detail']})")
    lines.append("통과시키려고 테스트를 지우거나 약하게 만든 것이면 [P1] 로 지적해라. "
                 "IMPLEMENTATION_NOTES.md 에 타당한 이유가 있으면 지적하지 않는다.")
    return "\n".join(lines)
