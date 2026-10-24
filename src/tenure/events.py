"""실행별 이벤트 기록 (DESIGN.md 36.3).

`.tenure/runs/<실행>/events.jsonl` 에 한 줄에 하나씩, 순번(seq)을 붙여 덧붙인다. 상태 전환·단계 시작/끝·로그가
모두 여기에 남아, 화면은 '마지막으로 본 seq 다음'만 받아 가면 된다(SSE 또는 폴링). 순번이 끊기면(파일을 다시
만들었거나 놓쳤으면) 받는 쪽은 실행 상세를 다시 읽는다.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path
from typing import Any

EVENTS_FILE = "events.jsonl"
MAX_READ = 1000

# kind 값
STATE = "state"            # status·phase·step 이 바뀜
STEP_START = "step_start"  # 에이전트 호출 시작
STEP_END = "step_end"      # 에이전트 호출 끝 (outcome·reason)
LOG = "log"                # 콘솔에 찍힌 줄
ATTENTION = "attention"    # 사람이 볼 일 (한도 대기, 실패, 미승인 …)


def _last_seq(path: Path) -> int:
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 65536))
            lines = f.read().splitlines()
    except OSError:
        return 0
    for line in reversed(lines):
        try:
            return int(json.loads(line)["seq"])
        except (ValueError, KeyError, TypeError):
            continue
    return 0


class EventLog:
    def __init__(self, run_dir: Path):
        self.path = Path(run_dir) / EVENTS_FILE
        self._lock = threading.Lock()
        self._seq = _last_seq(self.path)

    def emit(self, kind: str, **data: Any) -> dict[str, Any]:
        with self._lock:
            self._seq += 1
            rec = {"seq": self._seq, "ts": dt.datetime.now().isoformat(timespec="seconds"), "kind": kind, **data}
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            except OSError:
                pass                   # 기록 실패가 실행을 멈추게 하지 않는다
            return rec


_SHARED: dict[str, EventLog] = {}
_SHARED_LOCK = threading.Lock()


def for_run(run_dir: Path) -> EventLog:
    """같은 실행 폴더는 같은 EventLog 를 쓴다(한 프로세스 안에서 seq 가 겹치지 않게)."""
    key = str(Path(run_dir).resolve())
    with _SHARED_LOCK:
        log = _SHARED.get(key)
        if log is None:
            log = _SHARED[key] = EventLog(Path(run_dir))
        return log


def read_events(run_dir: Path, since: int = 0, limit: int = MAX_READ) -> list[dict[str, Any]]:
    """seq > since 인 이벤트를 순서대로 (최대 limit 개)."""
    path = Path(run_dir) / EVENTS_FILE
    out: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if int(rec.get("seq", 0)) > since:
                    out.append(rec)
                    if len(out) >= limit:
                        break
    except OSError:
        return []
    return out


def last_event(run_dir: Path) -> dict[str, Any] | None:
    path = Path(run_dir) / EVENTS_FILE
    seq = _last_seq(path)
    if not seq:
        return None
    evs = read_events(run_dir, since=seq - 1, limit=1)
    return evs[0] if evs else None
