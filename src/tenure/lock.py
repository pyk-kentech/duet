"""작업 폴더 단위 실행 잠금. <workdir>/.tenure/lock.json

같은 작업 폴더에서 tenure run/resume 이 동시에 돌면 git 커밋과 run.json 이 꼬인다.
잠금 파일에는 실행 중인 tenure 의 pid 와 run_id 가 들어 있고, UI 는 이걸로
'지금 살아 있는 실행'과 중지 대상 pid 를 안다.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from tenure import stopflag
from tenure.procs import replace_file
from tenure.runner import pid_alive
from tenure.state import project_dir

LOCK_FILENAME = "lock.json"


class LockBusy(Exception):
    def __init__(self, info: "LockInfo"):
        self.info = info
        super().__init__(
            f"이 작업 폴더에서 이미 tenure 가 실행 중입니다 (pid {info.pid}, 실행 {info.run_id or '?'}, "
            f"시작 {info.started_at}). 끝나거나 중지된 뒤 다시 시도하세요."
        )


@dataclass
class LockInfo:
    pid: int
    run_id: str | None
    started_at: str
    command: str = ""


def lock_path(workdir: Path) -> Path:
    return project_dir(workdir) / LOCK_FILENAME


def read_lock(workdir: Path) -> LockInfo | None:
    """살아 있는 잠금만 돌려준다. 죽은 프로세스가 남긴 잠금은 None."""
    path = lock_path(workdir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        info = LockInfo(**{k: data.get(k) for k in ("pid", "run_id", "started_at", "command")})
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(info.pid, int) or not pid_alive(info.pid):
        return None
    return info


class RunLock:
    """with RunLock(workdir, command) as lock: ...; lock.set_run(run_id)"""

    def __init__(self, workdir: Path, command: str = ""):
        self.path = lock_path(workdir)
        self.info = LockInfo(pid=os.getpid(), run_id=None,
                             started_at=dt.datetime.now().isoformat(timespec="seconds"), command=command)
        self.held = False

    def acquire(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                live = read_lock(self.path.parent.parent)
                if live is not None and live.pid != os.getpid():
                    raise LockBusy(live)
                # 죽은 잠금 → 지우고 다시
                self.path.unlink(missing_ok=True)
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(asdict(self.info), f, ensure_ascii=False)
            self.held = True
            stopflag.watch(self.path.parent.parent)      # 중지 요청 파일 (DESIGN.md 27.3)
            return self
        live = read_lock(self.path.parent.parent)
        raise LockBusy(live or self.info)

    def set_run(self, run_id: str) -> None:
        self.info.run_id = run_id
        if self.held:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(self.info), ensure_ascii=False), encoding="utf-8")
            replace_file(tmp, self.path)

    def release(self) -> None:
        if not self.held:
            return
        stopflag.unwatch()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("pid") == os.getpid():
                self.path.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
        self.held = False

    def __enter__(self) -> "RunLock":
        return self.acquire()

    def __exit__(self, *exc: object) -> None:
        self.release()
