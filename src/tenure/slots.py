"""동시에 띄우는 에이전트 CLI 수의 상한 (DESIGN.md 36.18).

이 머신의 모든 tenure 프로세스가 `$TENURE_HOME/slots/slot-<n>.lock` 을 나눠 쓴다. 에이전트 하나를 띄우는 동안
슬롯 파일 하나에 OS 잠금을 건다. 프로세스가 죽으면 OS 가 잠금을 풀어 주므로 남는 슬롯이 없다.
한도 대기·테스트 같은 다른 일은 슬롯을 잡지 않는다(에이전트 프로세스가 도는 동안만).
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from tenure import stopflag
from tenure.registry import tenure_home

SLOTS_DIR = "slots"
AUTO_MIN, AUTO_MAX = 2, 8
WAIT_POLL_SEC = 1.0

if os.name == "nt":
    import msvcrt

    def _try_lock(f) -> bool:
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(f) -> None:
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _try_lock(f) -> bool:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock(f) -> None:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


def resolve(limit: int) -> int:
    """설정값 → 실제 상한. 0 = 자동(논리 코어의 절반, 2~8)."""
    if limit > 0:
        return limit
    return max(AUTO_MIN, min(AUTO_MAX, (os.cpu_count() or 4) // 2))


def slots_dir(home: Path | None = None) -> Path:
    return (home or tenure_home()) / SLOTS_DIR


def in_use(limit: int, home: Path | None = None) -> int:
    """지금 잡힌 슬롯 수 (화면 표시용). 잠금을 잠깐 걸어 보고 바로 푼다."""
    d, n, busy = slots_dir(home), resolve(limit), 0
    for i in range(n):
        p = d / f"slot-{i}.lock"
        if not p.exists():
            continue
        try:
            with p.open("a+b") as f:
                if _try_lock(f):
                    _unlock(f)
                else:
                    busy += 1
        except OSError:
            pass
    return busy


@contextmanager
def agent_slot(limit: int, *, log: Callable[[str], None] | None = None, what: str = "",
               home: Path | None = None, poll: float = WAIT_POLL_SEC) -> Iterator[int]:
    """빈 슬롯을 잡을 때까지 기다린다. 슬롯 번호를 돌려준다. 중지 요청이면 기다리다 멈춘다."""
    n = resolve(limit)
    d = slots_dir(home)
    d.mkdir(parents=True, exist_ok=True)
    held = None
    waited_at: float | None = None
    while held is None:
        for i in range(n):
            f = (d / f"slot-{i}.lock").open("a+b")
            if _try_lock(f):
                held = (i, f)
                break
            f.close()
        if held is None:
            if waited_at is None:
                waited_at = time.monotonic()
                if log:
                    log(f"동시 실행 상한 {n}개가 모두 쓰이는 중이라 기다립니다" + (f" ({what})" if what else ""))
            stopflag.check()
            time.sleep(poll)
    if waited_at is not None and log:
        log(f"자리가 나서 시작합니다 ({time.monotonic() - waited_at:.0f}초 기다림)")
    i, f = held
    try:
        yield i
    finally:
        _unlock(f)
        f.close()
