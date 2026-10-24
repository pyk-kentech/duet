"""과제 첨부 파일 (DESIGN.md 33.3): 검사, 실행 폴더로 복사, 프롬프트 안내."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Iterable, Sequence

from tenure.tools import IMAGE_SUFFIXES

ATTACH_DIR = "attachments"
MAX_FILES = 10
MAX_TOTAL_BYTES = 20 * 1024 * 1024
# 첨부를 보여 주는 단계 (설계·구현·리뷰)
ATTACH_STEPS = ("propose", "critique", "synthesize", "implement", "fix", "review")
_UNSAFE = re.compile(r"[^\w.\- ]+", re.UNICODE)


class AttachmentError(ValueError):
    pass


def safe_name(name: str) -> str:
    base = Path(str(name)).name.strip()
    base = _UNSAFE.sub("_", base).strip(" .") or "file"
    return base[:120]


def check(paths: Sequence[Path]) -> list[Path]:
    """있는 파일인지, 개수·크기가 한도 안인지. 실행을 만들기 전에 부른다."""
    out = [Path(p).expanduser() for p in paths]
    if len(out) > MAX_FILES:
        raise AttachmentError(f"첨부는 {MAX_FILES}개까지입니다 ({len(out)}개).")
    total = 0
    for p in out:
        if not p.is_file():
            raise AttachmentError(f"첨부 파일이 없습니다: {p}")
        total += p.stat().st_size
    if total > MAX_TOTAL_BYTES:
        raise AttachmentError(f"첨부는 합쳐서 {MAX_TOTAL_BYTES // (1024 * 1024)}MB 까지입니다.")
    return out


def copy_into(run_dir: Path, paths: Iterable[Path]) -> list[str]:
    """실행 폴더의 attachments/ 로 복사하고 실행 폴더 기준 경로를 돌려준다(이름이 겹치면 번호)."""
    dest = Path(run_dir) / ATTACH_DIR
    names: list[str] = []
    for p in paths:
        dest.mkdir(parents=True, exist_ok=True)
        name = safe_name(p.name)
        stem, suf = Path(name).stem, Path(name).suffix
        n = 2
        while (dest / name).exists():
            name = f"{stem}-{n}{suf}"
            n += 1
        shutil.copyfile(p, dest / name)
        names.append(f"{ATTACH_DIR}/{name}")
    return names


def is_image(path: str | Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_SUFFIXES


def prompt_note(rel_paths: Sequence[str]) -> str:
    lines = "\n".join(f"- {p}" + (" (이미지)" if is_image(p) else "") for p in rel_paths)
    return ("## 첨부 파일 (사용자가 과제와 함께 준 자료)\n\n" + lines + "\n\n"
            "과제를 이해하는 데 필요하면 열어 봐라. 이미지·PDF 는 파일을 열어서 직접 봐라.")
