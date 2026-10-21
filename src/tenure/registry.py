"""관리자 UI 가 보여줄 프로젝트(작업 폴더) 목록. $TENURE_HOME/projects.json (기본 ~/.tenure)

`tenure run` / `tenure resume` 은 실행한 작업 폴더를 자동으로 등록한다.
등록 해제는 목록에서만 빼며 파일은 건드리지 않는다.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
from pathlib import Path

from tenure.procs import replace_file

REGISTRY_FILENAME = "projects.json"
_lock = threading.Lock()


def tenure_home() -> Path:
    env = os.environ.get("TENURE_HOME")
    if env:
        return Path(env).expanduser()
    from tenure.legacy import migrate_dir

    return migrate_dir(Path.home() / ".tenure", Path.home() / ".duet")   # 옛 ~/.duet 은 옮긴다 (36.11)


class Registry:
    def __init__(self, home: Path | None = None):
        self.home = Path(home) if home else tenure_home()
        self.path = self.home / REGISTRY_FILENAME

    def _load(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        items = data.get("projects", []) if isinstance(data, dict) else []
        return [x for x in items if isinstance(x, dict) and isinstance(x.get("path"), str)]

    def _save(self, items: list[dict]) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"projects": items}, ensure_ascii=False, indent=2), encoding="utf-8")
        replace_file(tmp, self.path)

    def list(self) -> list[str]:
        with _lock:
            return [x["path"] for x in self._load()]

    def contains(self, path: str | Path) -> bool:
        return normalize(path) in self.list()

    def add(self, path: str | Path) -> str:
        p = normalize(path)
        with _lock:
            items = self._load()
            if not any(x["path"] == p for x in items):
                items.append({"path": p, "added_at": dt.datetime.now().isoformat(timespec="seconds")})
                self._save(items)
        return p

    def remove(self, path: str | Path) -> bool:
        p = normalize(path)
        with _lock:
            items = self._load()
            kept = [x for x in items if x["path"] != p]
            if len(kept) == len(items):
                return False
            self._save(kept)
            return True


def normalize(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def register_quietly(path: str | Path) -> None:
    """실행 흐름을 막지 않도록 실패는 무시한다."""
    try:
        Registry().add(path)
    except OSError:
        pass
