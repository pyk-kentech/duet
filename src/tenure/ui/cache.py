"""대시보드 읽기 캐시 (DESIGN.md 36.18).

화면은 4~5초마다 프로젝트 목록·받은편지함을 다시 부른다. 매번 모든 run.json·이벤트 기록을 다시 읽고 풀던 것을,
파일의 (수정 시각, 크기)가 그대로면 기억한 값으로 돌려준다. 쓰기는 늘 파일로 하므로(원자적 교체) 키가 바뀌면 다시 읽는다.
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Hashable

from tenure.state import RUN_JSON, runs_root

MAX_ENTRIES = 4096
_MISSING = object()


def stat_key(path: Path) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


class StatCache:
    """경로 → (stat 키, 값). 키가 같으면 loader 를 부르지 않는다. 오래 안 쓴 것부터 버린다(LRU)."""

    def __init__(self, maxsize: int = MAX_ENTRIES):
        self.maxsize = maxsize
        self._d: OrderedDict[Hashable, tuple[Any, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = self.misses = 0

    def get(self, path: Path, loader: Callable[[Path], Any], key: Any = _MISSING) -> Any:
        k = str(path)
        key = stat_key(path) if key is _MISSING else key
        with self._lock:
            hit = self._d.get(k)
            if hit is not None and hit[0] == key:
                self._d.move_to_end(k)
                self.hits += 1
                return hit[1]
        value = loader(path)
        with self._lock:
            self.misses += 1
            self._d[k] = (key, value)
            self._d.move_to_end(k)
            while len(self._d) > self.maxsize:
                self._d.popitem(last=False)
        return value

    def __len__(self) -> int:
        return len(self._d)


class TtlCache:
    """짧은 시간 동안 같은 답을 쓴다(한 번의 폴링 안에서 같은 잠금 파일을 여러 번 보지 않게)."""

    def __init__(self, ttl: float = 1.0, maxsize: int = 1024):
        self.ttl, self.maxsize = ttl, maxsize
        self._d: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str, loader: Callable[[], Any]) -> Any:
        now = time.monotonic()
        with self._lock:
            hit = self._d.get(key)
            if hit is not None and now - hit[0] < self.ttl:
                return hit[1]
        value = loader()
        with self._lock:
            self._d[key] = (now, value)
            self._d.move_to_end(key)
            while len(self._d) > self.maxsize:
                self._d.popitem(last=False)
        return value


class RunDirs:
    """`.tenure/runs/` 의 실행 폴더 목록. 폴더의 수정 시각이 그대로면 다시 훑지 않는다.

    폴더를 만든 뒤 run.json 을 쓰기 전에 훑으면 그 폴더는 빠진다. 그런 폴더만 다음에 다시 확인한다.
    """

    def __init__(self, maxsize: int = 1024):
        self._c = StatCache(maxsize)

    def list(self, workdir: Path) -> list[Path]:
        root = runs_root(workdir)
        try:
            key = os.stat(root).st_mtime_ns
        except OSError:
            return []

        def scan(_: Path) -> dict[str, Any]:
            subs = sorted(p for p in root.iterdir() if p.is_dir())
            return {"subs": subs, "valid": {p for p in subs if (p / RUN_JSON).is_file()}}

        entry = self._c.get(root, scan, key=key)
        pending = [p for p in entry["subs"] if p not in entry["valid"]]
        for p in pending:
            if (p / RUN_JSON).is_file():
                entry["valid"].add(p)
        return [p for p in entry["subs"] if p in entry["valid"]]
