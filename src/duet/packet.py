"""리뷰 패킷: 리뷰어가 파일을 덜 열도록 diff 와 함께 미리 주는 문맥 (DESIGN.md 21.1).

- 함수 단위 문맥 diff 는 build.diff_body (git diff --function-context, 크기 제한을 넘으면 예전 diff).
- 바뀐 함수가 쓰이는 곳: diff 의 추가 줄·hunk 머리에서 정의된 이름을 모아 git grep.
"""

from __future__ import annotations

import re
from typing import Iterable

from duet.workspace import GitError, Workspace

DEF_RE = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:def|class|function|fn|func)\s+([A-Za-z_][A-Za-z0-9_]*)")
HUNK_RE = re.compile(r"^@@ [^@]* @@ ?(.*)$")
MAX_SYMBOLS = 15
PER_SYMBOL = 5
MAX_LINES = 40
LINE_CHARS = 160


def changed_symbols(diff_text: str) -> list[str]:
    """diff 에서 새로 정의되거나 바뀐 함수·클래스 이름 (등장 순, 최대 MAX_SYMBOLS)."""
    names: list[str] = []

    def add(line: str) -> None:
        m = DEF_RE.match(line)
        if m:
            name = m.group(1)
            if len(name) >= 3 and not (name.startswith("__") and name.endswith("__")) and name not in names:
                names.append(name)

    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            add(line[1:])
        else:
            m = HUNK_RE.match(line)
            if m:
                add(m.group(1))
        if len(names) >= MAX_SYMBOLS:
            break
    return names


def call_sites(ws: Workspace, symbols: Iterable[str], exclude: Iterable[str] = (),
               exclude_globs: Iterable[str] = ()) -> str:
    """이름마다 작업 폴더에서 쓰이는 줄 (정의 줄 제외). 없으면 빈 문자열."""
    exclude, exclude_globs = list(exclude), list(exclude_globs)
    blocks: list[str] = []
    total = 0
    for name in symbols:
        try:
            out = ws.git("grep", "-n", "-I", "-w", "--no-color", "-e", name, "--",
                         *Workspace._pathspec([".duet", *exclude], exclude_globs), check=False)
        except GitError:
            continue
        hits = []
        for line in out.splitlines():
            parts = line.split(":", 2)
            if len(parts) < 3 or DEF_RE.match(parts[2]):
                continue
            code = parts[2].strip()
            hits.append(f"  {parts[0]}:{parts[1]}: {code[:LINE_CHARS]}")
            if len(hits) >= PER_SYMBOL:
                break
        if not hits:
            continue
        if total + len(hits) > MAX_LINES:
            hits = hits[: max(0, MAX_LINES - total)]
            if not hits:
                break
        blocks.append(f"{name}:\n" + "\n".join(hits))
        total += len(hits)
    return "\n".join(blocks)


READ_INSTRUCTION_PACKET = (
    "위의 diff(바뀐 함수 전체가 들어 있다), 바뀐 함수가 쓰이는 곳, duet 테스트 결과로 먼저 판단해라. "
    "패킷만으로 판단할 수 없을 때만 꼭 필요한 파일을 열어라. diff 에 이미 있는 내용은 다시 열지 마라. "
    "아무 파일도 수정하지 마라."
)
READ_INSTRUCTION_PLAIN = "파일을 직접 열어봐도 된다. 필요한 파일만 골라 열어라. 단, 아무 파일도 수정하지 마라."
