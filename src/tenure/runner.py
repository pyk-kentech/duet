"""subprocess 실행 공통부.

tenure 안의 모든 외부 프로세스 실행(claude, codex, git, UI가 띄우는 tenure)은 이 모듈을 지난다.
타임아웃, 중단 처리, 실행 파일 부재를 여기서 한 번에 해결한다.

- 자식은 새 세션(프로세스 그룹)으로 띄운다. 타임아웃이나 중단(Ctrl-C, SIGTERM, 중지 요청 파일) 때
  트리 전체를 종료해서 claude/codex가 띄운 손자 프로세스(테스트, 셸 명령 등)가 남지 않게 한다.
- OS 별 차이는 procs.py 에 있다 (DESIGN.md 27장).
"""

from __future__ import annotations

import fnmatch
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Collection, Iterable, Mapping, Sequence

from tenure import procs, stopflag

log = logging.getLogger("tenure.runner")

# 타임아웃으로 강제 종료된 경우의 exit_code 표기값
TIMEOUT_EXIT_CODE = -1
# SIGTERM 후 SIGKILL 까지 기다리는 시간
KILL_GRACE_SEC = procs.KILL_GRACE_SEC
# 그룹을 죽인 뒤 남은 출력을 모으는 최대 시간
DRAIN_SEC = 5.0
# 프로세스가 정상 종료한 뒤 출력 파이프가 닫히기를 기다리는 시간
PIPE_GRACE_SEC = 2.0


class RunnerError(Exception):
    """실행부 공통 예외."""


class ExecutableNotFound(RunnerError):
    """실행 파일을 찾을 수 없음."""

    def __init__(self, executable: str):
        self.executable = executable
        super().__init__(f"실행 파일을 찾을 수 없습니다: {executable}")


@dataclass
class ProcessResult:
    cmd: list[str] | str
    stdout: str
    stderr: str
    exit_code: int
    duration_sec: float
    timed_out: bool = False
    stdin_text: str | None = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def augmented_path(path: str | None) -> str:
    """공식 설치 스크립트·npm 이 실행 파일을 두는 곳을 PATH 뒤에 붙인다 (procs.extra_bin_dirs)."""
    parts = [p for p in (path or "").split(os.pathsep) if p]
    for full in procs.extra_bin_dirs():
        if full not in parts:
            parts.append(full)
    return os.pathsep.join(parts)


def env_drops(strip: Iterable[str], keep: Iterable[str] = (),
              environ: Mapping[str, str] | None = None) -> list[str]:
    """environ(기본 os.environ)에서 strip 패턴(glob, 대소문자 무시)에 맞고 keep 에 없는 변수 이름."""
    environ = os.environ if environ is None else environ
    patterns = [p.upper() for p in strip]
    kept = {k.upper() for k in keep}
    return sorted(name for name in environ
                  if name.upper() not in kept
                  and any(fnmatch.fnmatchcase(name.upper(), p) for p in patterns))


def _merged_env(env: Mapping[str, str] | None, drop: Collection[str] = ()) -> dict[str, str]:
    full = {k: v for k, v in os.environ.items() if k not in drop}
    if env:
        full.update(env)
    full["PATH"] = augmented_path(full.get("PATH"))
    if procs.IS_WINDOWS:
        # 자식 파이썬(테스트, 가짜 CLI, 채점)의 표준 입출력을 UTF-8 로. 기본은 cp949 라 한글·이모지가 깨진다 (DESIGN.md 27.4)
        full.setdefault("PYTHONUTF8", "1")
    return full


def run_process(
    cmd: Sequence[str] | str,
    cwd: Path | str,
    *,
    timeout_sec: int | float | None = None,
    stdin_text: str | None = None,
    env: Mapping[str, str] | None = None,
    drop_env: Collection[str] = (),
) -> ProcessResult:
    """외부 명령을 실행하고 결과를 돌려준다.

    - stdin_text가 None이면 stdin을 /dev/null로 연결한다(대화형 대기 방지).
    - 타임아웃이 지나면 프로세스 그룹을 죽이고 timed_out=True 로 반환한다(예외 아님).
    - KeyboardInterrupt 등 예외가 나면 프로세스 그룹을 죽이고 예외를 다시 던진다.
    - 실행 파일이 없으면 ExecutableNotFound 를 던진다.
    - drop_env 의 이름은 상속 환경에서 뺀다(env 로 직접 준 값은 남김). 비밀 변수 정리용 (env_drops).
    - cmd 가 문자열이면 Windows 셸 명령줄이다 (procs.shell_argv).
    """
    cmd = cmd if isinstance(cmd, str) else [str(c) for c in cmd]
    log.debug("run: %s (cwd=%s, timeout=%s)", _fmt_cmd(cmd), cwd, timeout_sec)
    started = time.monotonic()
    full_env = _merged_env(env, set(drop_env))
    try:
        proc = subprocess.Popen(
            procs.resolve_argv(cmd, full_env.get("PATH")),
            cwd=str(cwd),
            stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=full_env,
            **procs.child_kwargs(),
        )
    except FileNotFoundError as e:
        raise ExecutableNotFound(cmd if isinstance(cmd, str) else cmd[0]) from e

    io = _PipeIO(proc, stdin_text)
    try:
        # communicate() 는 '파이프가 닫힐 때'까지 기다린다. 에이전트가 띄운 백그라운드 프로세스가
        # 출력 파이프를 물고 있으면 정상 종료한 호출도 타임아웃이 된다. 그래서 '프로세스 종료'를 기다린다.
        _wait(proc, timeout_sec)
    except subprocess.TimeoutExpired:
        log.warning("시간 초과(%ss): %s", timeout_sec, _fmt_cmd(cmd))
        kill_process_group(proc)
        stdout, stderr = io.finish(DRAIN_SEC)
        return ProcessResult(
            cmd=cmd, stdout=stdout, stderr=stderr, exit_code=TIMEOUT_EXIT_CODE,
            duration_sec=time.monotonic() - started, timed_out=True, stdin_text=stdin_text,
        )
    except BaseException:
        kill_process_group(proc)
        io.finish(DRAIN_SEC)
        raise

    stdout, stderr = io.finish(PIPE_GRACE_SEC)
    if io.leaked:
        # 리더는 끝났는데 같은 그룹의 자식이 파이프를 잡고 있다 → 정리
        log.warning("종료 후에도 출력 파이프를 잡은 하위 프로세스를 정리합니다: %s", _fmt_cmd(cmd))
        kill_process_group(proc)
        more_out, more_err = io.finish(DRAIN_SEC)
        stdout, stderr = more_out, more_err
    duration = time.monotonic() - started
    log.debug("done: exit=%s, %.1fs", proc.returncode, duration)
    return ProcessResult(
        cmd=cmd, stdout=stdout, stderr=stderr, exit_code=proc.returncode,
        duration_sec=duration, stdin_text=stdin_text,
    )


def _wait(proc: subprocess.Popen, timeout_sec: int | float | None) -> None:
    """프로세스 종료를 기다린다. 중지 요청 파일을 감시 중이면 짧게 나눠 기다리며 확인한다 (DESIGN.md 27.3).

    시간이 다 되면 TimeoutExpired, 중지 요청이면 KeyboardInterrupt.
    """
    if not stopflag.active():
        proc.wait(timeout=timeout_sec)
        return
    deadline = None if timeout_sec is None else time.monotonic() + timeout_sec
    while True:
        step = stopflag.POLL_SEC if deadline is None else max(0.0, min(stopflag.POLL_SEC, deadline - time.monotonic()))
        try:
            proc.wait(timeout=step)
            return
        except subprocess.TimeoutExpired:
            if deadline is not None and time.monotonic() >= deadline:
                raise
            stopflag.check()


class _PipeIO:
    """stdin 쓰기와 stdout/stderr 읽기를 스레드로 처리한다(서로 막지 않게)."""

    def __init__(self, proc: subprocess.Popen, stdin_text: str | None):
        self.proc = proc
        self.out: list[str] = []
        self.err: list[str] = []
        self.threads = [
            threading.Thread(target=self._read, args=(proc.stdout, self.out), daemon=True),
            threading.Thread(target=self._read, args=(proc.stderr, self.err), daemon=True),
        ]
        if stdin_text is not None:
            self.threads.append(threading.Thread(target=self._write, args=(stdin_text,), daemon=True))
        for t in self.threads:
            t.start()
        self.leaked = False

    @staticmethod
    def _read(pipe: IO[str] | None, sink: list[str]) -> None:
        if pipe is None:
            return
        try:
            while True:
                chunk = pipe.read(65536)
                if not chunk:
                    break
                sink.append(chunk)
        except (ValueError, OSError):
            pass

    def _write(self, text: str) -> None:
        pipe = self.proc.stdin
        if pipe is None:
            return
        try:
            pipe.write(text)
            pipe.close()
        except (BrokenPipeError, ValueError, OSError):
            pass

    def finish(self, grace: float) -> tuple[str, str]:
        """읽기 스레드가 끝나기를 grace 초까지 기다린다.

        파이프를 직접 닫지 않는다: 다른 스레드가 read() 중인 버퍼를 close() 하면 그 read 가
        끝날 때까지 막힌다. 대신 호출한 쪽이 프로세스 그룹을 죽여 파이프가 닫히게 한다.
        그래도 안 닫히면(그룹 밖으로 도망간 프로세스) 데몬 스레드를 버리고 지금까지 읽은 것만 돌려준다.
        """
        deadline = time.monotonic() + grace
        for t in self.threads:
            t.join(max(0.0, deadline - time.monotonic()))
        self.leaked = any(t.is_alive() for t in self.threads)
        return "".join(self.out), "".join(self.err)


def kill_process_group(proc: subprocess.Popen) -> None:
    """proc 과 그 자손을 모두 종료한다 (POSIX: 그룹 SIGTERM → SIGKILL, Windows: taskkill /T /F)."""
    procs.kill_tree(proc, KILL_GRACE_SEC)


def spawn_detached(
    cmd: Sequence[str],
    cwd: Path | str,
    *,
    log_file: IO[bytes],
    env: Mapping[str, str] | None = None,
) -> subprocess.Popen:
    """백그라운드로 띄우고 바로 돌아온다(UI 에서 tenure run/resume 실행용).

    호출한 쪽이 돌려받은 Popen 을 주기적으로 poll() 해서 좀비가 남지 않게 해야 한다.
    """
    cmd = [str(c) for c in cmd]
    log.debug("spawn: %s (cwd=%s)", _fmt_cmd(cmd), cwd)
    full_env = _merged_env(env)
    try:
        return subprocess.Popen(
            procs.resolve_argv(cmd, full_env.get("PATH")), cwd=str(cwd), stdin=subprocess.DEVNULL,
            stdout=log_file, stderr=subprocess.STDOUT, env=full_env, **procs.detached_kwargs(),
        )
    except FileNotFoundError as e:
        raise ExecutableNotFound(cmd[0]) from e


def pid_alive(pid: int) -> bool:
    return procs.pid_alive(pid)


def _as_text(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data


def _fmt_cmd(cmd: Sequence[str] | str, limit: int = 200) -> str:
    s = cmd if isinstance(cmd, str) else " ".join(cmd)
    return s if len(s) <= limit else s[:limit] + "…"


# ====================================================================== 대화형 터미널 (DESIGN.md 36.19)
class PtyProcessHandle:
    """가상 터미널에서 도는 자식. read() 는 글자(str)를 돌려주고, 끝나면 ''."""

    def __init__(self, argv: list[str], cwd: Path, env: dict[str, str], rows: int, cols: int):
        self.argv = argv
        if procs.IS_WINDOWS:
            from winpty import PtyProcess   # Windows ConPTY (pywinpty)

            self._p = PtyProcess.spawn(argv, cwd=str(cwd), env=env, dimensions=(rows, cols))
            self.pid = self._p.pid
        else:
            import codecs
            import fcntl
            import struct
            import termios

            master, slave = os.openpty()
            try:
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            except OSError:
                pass
            try:
                self._proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, cwd=str(cwd), env=env,
                                              start_new_session=True, close_fds=True)
            finally:
                os.close(slave)
            self._master = master
            self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            self.pid = self._proc.pid

    def read(self) -> str:
        if procs.IS_WINDOWS:
            try:
                return self._p.read(4096) or ""
            except EOFError:
                return ""
        try:
            data = os.read(self._master, 4096)
        except OSError:
            data = b""
        return self._decoder.decode(data, final=not data)

    def write(self, text: str) -> None:
        if procs.IS_WINDOWS:
            self._p.write(text)
        else:
            os.write(self._master, text.encode("utf-8"))

    def resize(self, rows: int, cols: int) -> None:
        if procs.IS_WINDOWS:
            self._p.setwinsize(rows, cols)
            return
        import fcntl
        import struct
        import termios

        fcntl.ioctl(self._master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def alive(self) -> bool:
        return self._p.isalive() if procs.IS_WINDOWS else self._proc.poll() is None

    def exit_code(self) -> int | None:
        if procs.IS_WINDOWS:
            return None if self._p.isalive() else self._p.exitstatus
        return self._proc.poll()

    def kill(self) -> None:
        if procs.IS_WINDOWS:
            procs.kill_pid_tree(self.pid)
            try:
                self._p.terminate(force=True)
            except Exception:  # noqa: BLE001 — 이미 끝났으면 무시
                pass
        elif self._proc.poll() is None:
            kill_process_group(self._proc)

    def close(self) -> None:
        if not procs.IS_WINDOWS:
            try:
                os.close(self._master)
            except OSError:
                pass


def spawn_pty(argv: Sequence[str], cwd: Path, env: Mapping[str, str] | None = None, *,
              rows: int = 30, cols: int = 120) -> PtyProcessHandle:
    """대화형 CLI 를 가상 터미널에서 띄운다(Windows ConPTY, 그 밖은 pty). 실행 파일이 없으면 ExecutableNotFound."""
    full = _merged_env({"TERM": "xterm-256color", "COLORTERM": "truecolor", **(env or {})})
    resolved = procs.resolve_argv(list(argv), full.get("PATH"))
    assert isinstance(resolved, list)
    if procs.IS_WINDOWS:
        if not Path(resolved[0]).is_file():
            raise ExecutableNotFound(f"실행 파일을 찾을 수 없습니다: {argv[0]}")
        if resolved[0].lower().endswith((".cmd", ".bat")):   # ConPTY 는 배치 파일을 바로 못 띄운다
            resolved = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", *resolved]
    try:
        return PtyProcessHandle(resolved, Path(cwd), full, rows, cols)
    except FileNotFoundError as e:
        raise ExecutableNotFound(f"실행 파일을 찾을 수 없습니다: {argv[0]}") from e
