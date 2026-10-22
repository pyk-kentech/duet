"""변경 사항의 줄 메모 (DESIGN.md 36.14, Daintree·Orca·Schaltwerk 의 아이디어).

실행 폴더의 `notes.json` 에 둔다. 줄 내용의 해시를 함께 둬 줄이 바뀌면 '오래됨'으로 본다.
'에이전트에게 보내기'는 열린 메모를 정해진 형식으로 구현 담당에게 넘긴다(phases.followup).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import uuid
from pathlib import Path

from tenure import procs
from tenure.workspace import GitError, Workspace

NOTES_FILE = "notes.json"
OPEN, SENT = "open", "sent"
NEW, OLD = "new", "old"          # 바뀐 뒤 줄 / 바뀌기 전 줄
MAX_NOTES = 200
MAX_TEXT = 4000
_PATH_RE = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[^\0]{1,400}$")


class NoteError(Exception):
    pass


def _path(run_dir: Path) -> Path:
    return Path(run_dir) / NOTES_FILE


def load(run_dir: Path) -> list[dict]:
    try:
        data = json.loads(_path(run_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [n for n in data if isinstance(n, dict) and n.get("id")] if isinstance(data, list) else []


def save(run_dir: Path, notes: list[dict]) -> None:
    path = _path(run_dir)
    tmp = path.with_name(NOTES_FILE + ".tmp")
    tmp.write_text(json.dumps(notes, ensure_ascii=False, indent=1), encoding="utf-8")
    procs.replace_file(tmp, path)


def _hash(text: str | None) -> str | None:
    return None if text is None else hashlib.sha1(text.rstrip("\r\n").encode("utf-8")).hexdigest()[:12]


def line_text(code_dir: Path, file: str, line: int, side: str, base: str | None) -> str | None:
    """메모가 가리키는 줄의 지금 내용. 바뀌기 전 줄은 기준 커밋에서 읽는다. 없으면 None."""
    try:
        if side == OLD:
            if not base:
                return None
            text = Workspace(code_dir).git("show", f"{base}:{file}")
        else:
            p = Path(code_dir) / file
            if not p.resolve().is_relative_to(Path(code_dir).resolve()) or not p.is_file():
                return None
            text = p.read_text(encoding="utf-8", errors="replace")
    except (GitError, OSError, ValueError):
        return None
    lines = text.splitlines()
    return lines[line - 1] if 1 <= line <= len(lines) else None


def add(run_dir: Path, code_dir: Path, *, file: str, line: int, side: str, text: str, base: str | None) -> dict:
    file = str(file or "").replace("\\", "/").strip()
    if not _PATH_RE.match(file):
        raise NoteError("파일 경로가 잘못되었습니다.")
    if side not in (NEW, OLD):
        raise NoteError("side 는 new 또는 old 입니다.")
    if not isinstance(line, int) or line < 1:
        raise NoteError("줄 번호가 잘못되었습니다.")
    text = str(text or "").strip()
    if not text:
        raise NoteError("메모를 입력하세요.")
    if len(text) > MAX_TEXT:
        raise NoteError(f"메모는 {MAX_TEXT}자까지입니다.")
    notes = load(run_dir)
    if len(notes) >= MAX_NOTES:
        raise NoteError(f"메모는 실행마다 {MAX_NOTES}개까지입니다.")
    content = line_text(code_dir, file, line, side, base)
    note = {"id": uuid.uuid4().hex[:10], "file": file, "line": line, "side": side, "text": text,
            "line_text": content, "line_hash": _hash(content), "status": OPEN, "sent_round": None,
            "created": dt.datetime.now().isoformat(timespec="seconds")}
    save(run_dir, [*notes, note])
    return note


def remove(run_dir: Path, note_id: str) -> bool:
    notes = load(run_dir)
    keep = [n for n in notes if n.get("id") != note_id]
    if len(keep) == len(notes):
        return False
    save(run_dir, keep)
    return True


def with_stale(run_dir: Path, code_dir: Path, base: str | None) -> list[dict]:
    """메모마다 stale(그 줄 내용이 메모를 단 뒤 바뀜)을 붙인다. 보낸 메모는 보지 않는다."""
    out = []
    for n in load(run_dir):
        stale = False
        if n.get("status") == OPEN:
            stale = _hash(line_text(code_dir, n["file"], int(n["line"]), n.get("side", NEW), base)) != n.get("line_hash")
        out.append({**n, "stale": stale})
    return out


def open_notes(run_dir: Path) -> list[dict]:
    return [n for n in load(run_dir) if n.get("status") == OPEN]


def format_for_prompt(items: list[dict]) -> str:
    blocks = []
    for i, n in enumerate(items, 1):
        where = f"{n['file']}:{n['line']}" + (" (바뀌기 전 줄)" if n.get("side") == OLD else "")
        quoted = (n.get("line_text") or "").strip()
        blocks.append(f"{i}. {where}\n   줄: {quoted or '(내용 없음)'}\n   메모: {n['text']}")
    return "\n".join(blocks)


def mark_sent(run_dir: Path, ids: set[str], round_no: int) -> None:
    notes = load(run_dir)
    for n in notes:
        if n.get("id") in ids:
            n["status"], n["sent_round"] = SENT, round_no
    save(run_dir, notes)
