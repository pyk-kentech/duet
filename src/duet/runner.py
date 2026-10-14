"""subprocess 실행 공통부.

duet 안의 모든 외부 프로세스 실행(claude, codex, git)은 이 모듈의 `run_process()`
한 곳을 지난다. 타임아웃, 로깅, 실행 파일 부재 처리를 여기서 한 번에 해결한다.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

log = logging.getLogger("duet.runner")


class RunnerError(Exception):
    """실행부 공통 예외."""


class ExecutableNotFound(RunnerError):
    """실행 파일을 찾을 수 없음."""

    def __init__(self, executable: str):
        self.executable = executable
        super().__init__(f"실행 파일을 찾을 수 없습니다: {executable}")


@dataclass
class ProcessResult:
    cmd: list[str]
    stdout: str
    stderr: str
    exit_code: int
    duration_sec: float
    timed_out: bool = False
    stdin_text: str | None = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


# 타임아웃으로 강제 종료된 경우의 exit_code 표기값
TIMEOUT_EXIT_CODE = -1


def run_process(
    cmd: Sequence[str],
    cwd: Path | str,
    *,
    timeout_sec: int | None = None,
    stdin_text: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ProcessResult:
    """외부 명령을 실행하고 결과를 돌려준다.

    - stdin_text가 None이면 stdin을 /dev/null로 연결한다(대화형 대기 방지).
    - 타임아웃이 지나면 프로세스를 죽이고 timed_out=True 로 반환한다(예외 아님).
    - 실행 파일이 없으면 ExecutableNotFound 를 던진다.
    """
    cmd = [str(c) for c in cmd]
    cwd = str(cwd)
    full_env = dict(os.environ)
    if env:
        full_env.update(env)

    log.debug("run: %s (cwd=%s, timeout=%s)", _fmt_cmd(cmd), cwd, timeout_sec)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            cmd,
            cwd=cwd,
            input=stdin_text,
            stdin=None if stdin_text is not None else subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            env=full_env,
        )
    except FileNotFoundError as e:
        raise ExecutableNotFound(cmd[0]) from e
    except subprocess.TimeoutExpired as e:
        duration = time.monotonic() - started
        log.warning("시간 초과(%ss): %s", timeout_sec, _fmt_cmd(cmd))
        return ProcessResult(
            cmd=cmd,
            stdout=_as_text(e.stdout),
            stderr=_as_text(e.stderr),
            exit_code=TIMEOUT_EXIT_CODE,
            duration_sec=duration,
            timed_out=True,
            stdin_text=stdin_text,
        )

    duration = time.monotonic() - started
    log.debug("done: exit=%s, %.1fs", completed.returncode, duration)
    return ProcessResult(
        cmd=cmd,
        stdout=completed.stdout,
        stderr=completed.stderr,
        exit_code=completed.returncode,
        duration_sec=duration,
        stdin_text=stdin_text,
    )


def _as_text(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data


def _fmt_cmd(cmd: Sequence[str], limit: int = 200) -> str:
    s = " ".join(cmd)
    return s if len(s) <= limit else s[:limit] + "…"
