"""subprocess 실행 공통부.

duet 안의 모든 외부 프로세스 실행(claude, codex, git, UI가 띄우는 duet)은 이 모듈을 지난다.
타임아웃, 중단 처리, 실행 파일 부재를 여기서 한 번에 해결한다.

- 자식은 새 세션(프로세스 그룹)으로 띄운다. 타임아웃이나 중단(Ctrl-C, SIGTERM) 때
  그룹 전체를 종료해서 claude/codex가 띄운 손자 프로세스(테스트, 셸 명령 등)가 남지 않게 한다.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Mapping, Sequence

log = logging.getLogger("duet.runner")

# 타임아웃으로 강제 종료된 경우의 exit_code 표기값
TIMEOUT_EXIT_CODE = -1
# SIGTERM 후 SIGKILL 까지 기다리는 시간
KILL_GRACE_SEC = 3.0
# 그룹을 죽인 뒤 남은 출력을 모으는 최대 시간
DRAIN_SEC = 5.0


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


def _merged_env(env: Mapping[str, str] | None) -> dict[str, str]:
    full = dict(os.environ)
    if env:
        full.update(env)
    return full


def run_process(
    cmd: Sequence[str],
    cwd: Path | str,
    *,
    timeout_sec: int | float | None = None,
    stdin_text: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ProcessResult:
    """외부 명령을 실행하고 결과를 돌려준다.

    - stdin_text가 None이면 stdin을 /dev/null로 연결한다(대화형 대기 방지).
    - 타임아웃이 지나면 프로세스 그룹을 죽이고 timed_out=True 로 반환한다(예외 아님).
    - KeyboardInterrupt 등 예외가 나면 프로세스 그룹을 죽이고 예외를 다시 던진다.
    - 실행 파일이 없으면 ExecutableNotFound 를 던진다.
    """
    cmd = [str(c) for c in cmd]
    log.debug("run: %s (cwd=%s, timeout=%s)", _fmt_cmd(cmd), cwd, timeout_sec)
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_merged_env(env),
            start_new_session=True,
        )
    except FileNotFoundError as e:
        raise ExecutableNotFound(cmd[0]) from e

    try:
        stdout, stderr = proc.communicate(stdin_text, timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        log.warning("시간 초과(%ss): %s", timeout_sec, _fmt_cmd(cmd))
        kill_process_group(proc)
        stdout, stderr = _drain(proc)
        return ProcessResult(
            cmd=cmd, stdout=stdout, stderr=stderr, exit_code=TIMEOUT_EXIT_CODE,
            duration_sec=time.monotonic() - started, timed_out=True, stdin_text=stdin_text,
        )
    except BaseException:
        kill_process_group(proc)
        _drain(proc)
        raise

    duration = time.monotonic() - started
    log.debug("done: exit=%s, %.1fs", proc.returncode, duration)
    return ProcessResult(
        cmd=cmd, stdout=stdout, stderr=stderr, exit_code=proc.returncode,
        duration_sec=duration, stdin_text=stdin_text,
    )


def kill_process_group(proc: subprocess.Popen) -> None:
    """proc 이 이끄는 프로세스 그룹 전체를 SIGTERM → (유예) → SIGKILL 로 종료한다."""
    pgid = proc.pid
    if not hasattr(os, "killpg"):  # pragma: no cover - Windows
        proc.kill()
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=KILL_GRACE_SEC)
    except subprocess.TimeoutExpired:
        pass
    # 리더가 먼저 끝났어도 그룹에 남은 손자 프로세스가 있을 수 있다
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _drain(proc: subprocess.Popen) -> tuple[str, str]:
    """죽인 프로세스의 남은 출력을 모은다. 그룹 밖으로 도망간 프로세스가 파이프를 잡고 있으면 포기한다."""
    try:
        out, err = proc.communicate(timeout=DRAIN_SEC)
        return out or "", err or ""
    except subprocess.TimeoutExpired as e:
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            try:
                if pipe:
                    pipe.close()
            except OSError:
                pass
        try:
            proc.wait(timeout=DRAIN_SEC)
        except subprocess.TimeoutExpired:
            pass
        return _as_text(e.stdout), _as_text(e.stderr)
    except (ValueError, OSError):
        return "", ""


def spawn_detached(
    cmd: Sequence[str],
    cwd: Path | str,
    *,
    log_file: IO[bytes],
    env: Mapping[str, str] | None = None,
) -> subprocess.Popen:
    """백그라운드로 띄우고 바로 돌아온다(UI 에서 duet run/resume 실행용).

    호출한 쪽이 돌려받은 Popen 을 주기적으로 poll() 해서 좀비가 남지 않게 해야 한다.
    """
    cmd = [str(c) for c in cmd]
    log.debug("spawn: %s (cwd=%s)", _fmt_cmd(cmd), cwd)
    try:
        return subprocess.Popen(
            cmd, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT,
            env=_merged_env(env), start_new_session=True,
        )
    except FileNotFoundError as e:
        raise ExecutableNotFound(cmd[0]) from e


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # 좀비는 살아 있는 것으로 치지 않는다 (Linux)
    stat = Path(f"/proc/{pid}/stat")
    try:
        state = stat.read_text().rsplit(")", 1)[1].split()[0]
        return state != "Z"
    except (OSError, IndexError):
        return True


def _as_text(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data


def _fmt_cmd(cmd: Sequence[str], limit: int = 200) -> str:
    s = " ".join(cmd)
    return s if len(s) <= limit else s[:limit] + "…"
