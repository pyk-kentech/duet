"""리뷰어가 제출하는 '재현 테스트'.

리뷰어는 읽기 전용이라 파일을 못 쓴다. 대신 리뷰 응답에

    <repro path="tests/test_repro_empty_tag.py">
    ...실패하는 테스트 코드...
    </repro>

블록을 넣으면 tenure 가 검증해서 작업 폴더에 새 파일로 저장·커밋하고, 실제로 실패하는지 돌려 본다.
구현자는 다음 라운드에 이 테스트를 통과시켜야 한다. 말로 하는 지적 대신 통과·실패로 정리된다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

REPRO_RE = re.compile(r"<repro\s+path\s*=\s*[\"']([^\"'>]+)[\"']\s*>\s*\n?(.*?)</repro>", re.DOTALL | re.IGNORECASE)
MAX_BLOCKS = 5
MAX_BYTES = 20_000
FORBIDDEN_TOP = {".tenure", ".duet", ".git"}


@dataclass
class ReproFile:
    path: str
    content: str


@dataclass
class ReproParse:
    files: list[ReproFile] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)   # 사람이 읽을 거절 사유


def _strip_fence(code: str) -> str:
    """블록 안에 ```python ... ``` 펜스를 또 넣은 경우 벗긴다."""
    s = code.strip("\n")
    m = re.match(r"^\s*```[\w+-]*\s*\n(.*?)\n\s*```\s*$", s, re.DOTALL)
    return (m.group(1) if m else s).rstrip() + "\n"


def parse_repros(text: str, workdir: Path) -> ReproParse:
    out = ReproParse()
    wd = workdir.resolve()
    for raw_path, code in REPRO_RE.findall(text or ""):
        rel = raw_path.strip()
        if len(out.files) >= MAX_BLOCKS:
            out.rejected.append(f"{rel}: 한 번에 {MAX_BLOCKS}개까지만 받습니다")
            continue
        p = PurePosixPath(rel)
        if p.is_absolute() or ".." in p.parts or not p.parts or p.parts[0] in FORBIDDEN_TOP or rel.startswith("~"):
            out.rejected.append(f"{rel}: 작업 폴더 안의 상대 경로여야 합니다")
            continue
        if not re.search(r"test", p.name, re.IGNORECASE) and not any(re.search(r"test|spec", part, re.IGNORECASE) for part in p.parts[:-1]):
            out.rejected.append(f"{rel}: 테스트 파일로 보이지 않습니다(이름이나 폴더에 test 가 있어야 함)")
            continue
        target = (wd / rel).resolve()
        if wd not in target.parents:
            out.rejected.append(f"{rel}: 작업 폴더 밖입니다")
            continue
        if target.exists():
            out.rejected.append(f"{rel}: 이미 있는 파일은 덮어쓰지 않습니다(새 파일만)")
            continue
        content = _strip_fence(code)
        if len(content.encode("utf-8")) > MAX_BYTES:
            out.rejected.append(f"{rel}: 너무 깁니다({MAX_BYTES // 1000}KB 까지)")
            continue
        if any(f.path == rel for f in out.files):
            out.rejected.append(f"{rel}: 같은 경로가 두 번 나왔습니다")
            continue
        out.files.append(ReproFile(rel, content))
    return out


def write_repros(files: list[ReproFile], workdir: Path) -> list[str]:
    written = []
    for f in files:
        target = workdir / f.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.content, encoding="utf-8")
        written.append(f.path)
    return written
