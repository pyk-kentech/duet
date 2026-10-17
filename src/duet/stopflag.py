"""중지 요청 파일 (DESIGN.md 27.3).

UI 의 중지는 <workdir>/.duet/stop 을 만든다. 실행 중인 duet 는 잠금을 잡을 때 이 파일을 감시 대상으로 등록하고,
에이전트 호출을 기다리는 동안·한도 대기 중·단계 사이에 보고, 있으면 KeyboardInterrupt 로 멈춘다(Ctrl-C 와 같은 경로).
Windows 에는 다른 프로세스에 보낼 SIGTERM 이 없어서 모든 OS 에서 이 방식을 쓴다(POSIX 는 SIGTERM 도 함께).
"""

from __future__ import annotations

from pathlib import Path

from duet.state import DUET_DIR

STOP_FILENAME = "stop"
POLL_SEC = 0.5

_watched: Path | None = None


def stop_path(workdir: Path) -> Path:
    return Path(workdir) / DUET_DIR / STOP_FILENAME


def request(workdir: Path) -> Path:
    path = stop_path(workdir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stop\n", encoding="utf-8")
    return path


def watch(workdir: Path) -> None:
    """이 프로세스가 workdir 의 중지 요청을 따른다. 예전에 남은 요청은 지운다."""
    global _watched
    _watched = stop_path(workdir)
    _watched.unlink(missing_ok=True)


def unwatch() -> None:
    global _watched
    if _watched is not None:
        _watched.unlink(missing_ok=True)
    _watched = None


def active() -> bool:
    return _watched is not None


def requested() -> bool:
    return _watched is not None and _watched.exists()


def check() -> None:
    if requested():
        raise KeyboardInterrupt
