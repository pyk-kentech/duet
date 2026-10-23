"""작업공간의 파일·git 보기 (DESIGN.md 36.22): 오른쪽 판의 파일 트리, 파일 보기, 바뀐 파일, 파일별 차이.

작업공간 = 등록된 프로젝트 폴더 또는 그 실행의 worktree. 경로는 반드시 그 폴더 안으로만 푼다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from tenure.runner import ExecutableNotFound, run_process

HIDDEN = {".git", ".tenure", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
HEAVY = {"node_modules", ".venv", "venv", "target", "dist", "build", ".next", ".cache"}   # 보이되 펼칠 때만 읽음
MAX_ENTRIES = 2000
MAX_FILE_BYTES = 1_000_000
MAX_DIFF_BYTES = 400_000
GIT_TIMEOUT = 20


class FilesError(Exception):
    """사용자에게 그대로 보여 줄 메시지."""


def safe_path(root: Path, rel: str | None) -> Path:
    """root 안의 경로만 허용한다 (.., 절대 경로, 심볼릭 링크로 밖으로 나가기 금지)."""
    rel = (rel or "").replace("\\", "/").strip("/")
    if rel and (rel.startswith("/") or ":" in rel.split("/")[0] or any(p == ".." for p in rel.split("/"))):
        raise FilesError("경로가 잘못되었습니다.")
    root_r = root.resolve()
    p = (root_r / rel).resolve() if rel else root_r
    if p != root_r and root_r not in p.parents:
        raise FilesError("작업공간 밖의 경로입니다.")
    return p


def tree(root: Path, rel: str | None = None) -> dict[str, Any]:
    """한 단계만 읽는다 (펼칠 때 다음 단계). 폴더 먼저, 이름 순."""
    d = safe_path(root, rel)
    if not d.is_dir():
        raise FilesError("폴더가 아닙니다.")
    entries = []
    try:
        with os.scandir(d) as it:
            for e in it:
                if e.name in HIDDEN:
                    continue
                try:
                    is_dir = e.is_dir()
                    size = 0 if is_dir else e.stat().st_size
                except OSError:
                    continue
                entries.append({"name": e.name, "dir": is_dir, "size": size, "heavy": is_dir and e.name in HEAVY})
                if len(entries) >= MAX_ENTRIES:
                    break
    except OSError as e:
        raise FilesError(f"폴더를 읽지 못했습니다: {e}") from e
    entries.sort(key=lambda x: (not x["dir"], x["name"].lower()))
    base = (rel or "").replace("\\", "/").strip("/")
    return {"path": base, "entries": entries, "truncated": len(entries) >= MAX_ENTRIES}


def read_file(root: Path, rel: str) -> dict[str, Any]:
    p = safe_path(root, rel)
    if not p.is_file():
        raise FilesError("파일이 아닙니다.")
    size = p.stat().st_size
    with p.open("rb") as f:
        data = f.read(MAX_FILE_BYTES + 1)
    truncated = len(data) > MAX_FILE_BYTES
    data = data[:MAX_FILE_BYTES]
    if b"\0" in data[:8192]:
        return {"path": rel, "size": size, "binary": True, "text": "", "truncated": False}
    return {"path": rel, "size": size, "binary": False, "text": data.decode("utf-8", errors="replace"), "truncated": truncated}


def _git(root: Path, *args: str) -> tuple[bool, str]:
    try:
        r = run_process(["git", "-c", "core.quotepath=false", *args], cwd=root, timeout_sec=GIT_TIMEOUT)
    except ExecutableNotFound:
        return False, "git 을 찾을 수 없습니다."
    return r.ok, r.stdout if r.ok else r.stderr


def status(root: Path) -> dict[str, Any]:
    """바뀐 파일 (작업 트리 + 스테이징, HEAD 기준) 과 줄 수. git 저장소가 아니면 repo=False."""
    ok, out = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if not ok:
        return {"repo": False, "branch": None, "files": []}
    branch = out.strip()
    ok, porcelain = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    files: dict[str, dict[str, Any]] = {}
    if ok:
        items = porcelain.split("\0")
        i = 0
        while i < len(items):
            rec = items[i]
            i += 1
            if len(rec) < 4:
                continue
            code, path = rec[:2], rec[3:]
            if code[0] in "RC":                  # 이름 바뀜: 다음 칸이 옛 이름
                i += 1
            kind = ("untracked" if code == "??" else "added" if "A" in code else "deleted" if "D" in code
                    else "renamed" if "R" in code else "modified")
            files[path] = {"path": path, "kind": kind, "add": 0, "del": 0}
    ok, numstat = _git(root, "diff", "--numstat", "HEAD")
    if ok:
        for line in numstat.splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[2] in files:
                a, d, _ = parts
                files[parts[2]]["add"] = int(a) if a.isdigit() else 0
                files[parts[2]]["del"] = int(d) if d.isdigit() else 0
    ok, ahead = _git(root, "log", "--oneline", "-n", "8", "--format=%h%x09%s%x09%cr")
    commits = [dict(zip(("short", "subject", "when"), x.split("\t"))) for x in ahead.splitlines() if x.count("\t") == 2] if ok else []
    return {"repo": True, "branch": branch, "files": sorted(files.values(), key=lambda f: f["path"]), "commits": commits}


def file_diff(root: Path, rel: str) -> dict[str, Any]:
    """한 파일의 HEAD 대비 차이. 새 파일은 전부 추가로 보인다."""
    p = safe_path(root, rel)
    rel_posix = p.relative_to(root.resolve()).as_posix()
    ok, tracked = _git(root, "ls-files", "--error-unmatch", "--", rel_posix)
    if ok:
        ok, text = _git(root, "diff", "--no-color", "HEAD", "--", rel_posix)
        if not ok:
            raise FilesError(f"차이를 읽지 못했습니다: {text.strip()[-300:]}")
    else:
        if not p.is_file():
            raise FilesError("파일이 없습니다.")
        body = read_file(root, rel_posix)
        if body["binary"]:
            text = f"(바이너리 새 파일: {rel_posix})"
        else:
            lines = body["text"].splitlines()
            text = (f"diff --git a/{rel_posix} b/{rel_posix}\nnew file\n--- /dev/null\n+++ b/{rel_posix}\n"
                    f"@@ -0,0 +1,{len(lines)} @@\n" + "".join(f"+{ln}\n" for ln in lines))
    truncated = len(text) > MAX_DIFF_BYTES
    return {"path": rel_posix, "text": text[:MAX_DIFF_BYTES], "truncated": truncated}
