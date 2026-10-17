"""관리자 UI 의 '터미널 작업': 설치·로그인 명령을 가상 터미널(pty)에서 돌리고 출력을 모은다.

- 로그인 명령은 TTY 를 요구하거나 화면을 그리므로 pty 를 쓴다.
- Windows 에는 pty 가 없다 (DESIGN.md 27.5): mode="pipe" 는 파이프로 돌려 출력을 모으고,
  mode="console" 은 새 콘솔 창에서 돌린다(로그인처럼 터미널 입력이 필요한 동작).
- 출력의 터미널 제어 문자(색, 커서 이동)는 지워서 텍스트로 보여준다.
- UI 에서 한 줄씩 입력(코드, sudo 비밀번호)을 보낼 수 있다.
- 실행 명령은 doctor.ACTIONS 에 정의된 것만. 임의 명령은 받지 않는다.
"""

from __future__ import annotations

import codecs
import datetime as dt
import os
import re
import struct
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any

from duet import procs
from duet.runner import _merged_env, kill_process_group

HAS_PTY = hasattr(os, "openpty")
CONSOLE_NOTE = "새 콘솔 창에서 실행했습니다. 그 창에서 안내를 따라 진행하고, 끝나면 창을 닫으세요."

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
URL_RE = re.compile(r"https?://[^\s<>\"'`]+")
MAX_BUFFER = 300_000


def clean(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = ANSI_RE.sub("", text)
    return text.replace("\r", "\n")


@dataclass
class TermJob:
    id: str
    title: str
    argv: list[str]
    machine: str = "local"
    note: str = ""
    mode: str = "pty"         # pty | pipe | console (DESIGN.md 27.5)
    started_at: str = field(default_factory=lambda: dt.datetime.now().isoformat(timespec="seconds"))
    text: str = ""
    dropped: int = 0          # 버퍼가 넘쳐서 앞에서 버린 글자 수
    returncode: int | None = None
    _proc: subprocess.Popen | None = None
    _master: int = -1
    _reader_thread: threading.Thread | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def start(self, cwd: str | None = None) -> "TermJob":
        if self.mode == "pty" and not HAS_PTY:
            self.mode = "pipe"
        if self.mode == "console":
            return self._start_console(cwd)
        if self.mode == "pipe":
            return self._start_pipe(cwd)
        import fcntl
        import termios

        master, slave = os.openpty()
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        except OSError:
            pass
        env = _merged_env({"TERM": "xterm-256color", "COLUMNS": "120", "LINES": "40", "NO_COLOR": "1"})
        try:
            self._proc = subprocess.Popen(self.argv, stdin=slave, stdout=slave, stderr=slave, cwd=cwd or os.path.expanduser("~"),
                                          env=env, start_new_session=True, close_fds=True)
        finally:
            os.close(slave)
        self._master = master
        self._reader_thread = threading.Thread(target=self._reader, daemon=True)
        self._reader_thread.start()
        return self

    def _start_pipe(self, cwd: str | None) -> "TermJob":
        env = _merged_env({"NO_COLOR": "1", "PYTHONIOENCODING": "utf-8"})
        self._proc = subprocess.Popen(procs.resolve_argv(self.argv, env.get("PATH")), stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      cwd=cwd or os.path.expanduser("~"), env=env, **procs.child_kwargs())
        self._reader_thread = threading.Thread(target=self._reader, daemon=True)
        self._reader_thread.start()
        return self

    def _start_console(self, cwd: str | None) -> "TermJob":
        self._proc = subprocess.Popen(procs.resolve_argv(self.argv), cwd=cwd or os.path.expanduser("~"),
                                      env=_merged_env(None), **procs.console_kwargs())
        self._append(CONSOLE_NOTE + "\n")
        self._reader_thread = threading.Thread(target=self._wait_console, daemon=True)
        self._reader_thread.start()
        return self

    def _wait_console(self) -> None:
        assert self._proc is not None
        rc = self._proc.wait()
        self._append(f"\n(창이 닫혔습니다. 종료 코드 {rc})\n")
        with self._lock:
            self.returncode = rc

    def _read_chunk(self) -> bytes:
        if self.mode == "pipe":
            assert self._proc is not None and self._proc.stdout is not None
            return self._proc.stdout.read1(4096) if hasattr(self._proc.stdout, "read1") else self._proc.stdout.read(4096)
        return os.read(self._master, 4096)

    def _reader(self) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while True:
            try:
                data = self._read_chunk()
            except (OSError, ValueError):
                break
            if not data:
                break
            self._append(clean(decoder.decode(data)))
        self._append(clean(decoder.decode(b"", final=True)))
        if self._proc is not None:
            rc = self._proc.wait()
            with self._lock:
                self.returncode = rc
        if self._master >= 0:
            try:
                os.close(self._master)
            except OSError:
                pass

    def _append(self, s: str) -> None:
        if not s:
            return
        with self._lock:
            self.text += s
            if len(self.text) > MAX_BUFFER:
                cut = len(self.text) - MAX_BUFFER
                self.text = self.text[cut:]
                self.dropped += cut

    @property
    def running(self) -> bool:
        """프로세스가 살아 있거나, 끝났지만 남은 출력을 아직 다 읽지 않았으면 True."""
        if self._proc is None:
            return False
        if self._proc.poll() is None:
            return True
        return self.returncode is None

    def write(self, line: str) -> None:
        if not self.running:
            raise RuntimeError("이미 끝난 작업입니다.")
        if self.mode == "console":
            raise RuntimeError("새 콘솔 창에서 실행 중입니다. 그 창에 직접 입력하세요.")
        if self.mode == "pipe":
            assert self._proc is not None and self._proc.stdin is not None
            self._proc.stdin.write(line.encode("utf-8") + b"\n")
            self._proc.stdin.flush()
            return
        os.write(self._master, line.encode("utf-8") + b"\r")

    def kill(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            kill_process_group(self._proc)

    def snapshot(self, offset: int = 0) -> dict[str, Any]:
        # 프로세스가 끝났으면 리더가 남은 출력을 다 붙일 때까지 기다린 뒤에 텍스트와 종료 코드를 함께 읽는다.
        # (먼저 텍스트를 읽고 나중에 종료 코드를 읽으면 '끝남'인데 마지막 줄이 빠진 상태가 보일 수 있다)
        if self._proc is not None and self._proc.poll() is not None and self._reader_thread is not None:
            self._reader_thread.join(2.0)
        with self._lock:
            start = max(0, offset - self.dropped)
            chunk = self.text[start:]
            end = self.dropped + len(self.text)
            urls = list(dict.fromkeys(URL_RE.findall(self.text)))[-5:]
            returncode = self.returncode
        running = returncode is None and self._proc is not None and self._proc.poll() is None
        return {"id": self.id, "title": self.title, "machine": self.machine, "note": self.note, "mode": self.mode,
                "started_at": self.started_at, "running": running, "returncode": returncode,
                "text": chunk, "offset": end, "urls": urls}
