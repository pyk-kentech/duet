"""브라우저 확인 (DESIGN.md 33.4): 웹 화면이 있는 결과물이면 앱을 띄우고 리뷰어에게 브라우저 도구를 붙인다.

필요할 때만: 웹 앱으로 보일 때만 켜고, 실제로 열지는 리뷰어가 판단한다.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from duet import procs
from duet.runner import ExecutableNotFound, augmented_path, spawn_detached
from duet.tools import Browser

START_TIMEOUT_SEC = 60.0
_URL_RE = re.compile(r"https?://(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]):(\d{2,5})")
LOG_NAME = "browser-app.log"


@dataclass
class WebApp:
    kind: str                        # "npm" | "static"
    command: list[str] = field(default_factory=list)
    port: int | None = None          # static 은 duet 가 정한 포트


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def detect(workdir: Path) -> WebApp | None:
    """웹 화면이 있는 프로젝트인가: package.json 의 dev/start 스크립트 + node_modules, 또는 최상위 index.html."""
    wd = Path(workdir)
    pkg = wd / "package.json"
    if pkg.is_file():
        try:
            scripts = (json.loads(pkg.read_text(encoding="utf-8")) or {}).get("scripts") or {}
        except (OSError, ValueError):
            scripts = {}
        script = "dev" if "dev" in scripts else "start" if "start" in scripts else None
        if script and (wd / "node_modules").is_dir():
            return WebApp("npm", ["npm", "run", script] if script == "dev" else ["npm", "start"])
    if (wd / "index.html").is_file():
        port = _free_port()
        return WebApp("static", [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"], port)
    return None


def playwright_tool(url: str) -> Browser | None:
    """Playwright MCP 를 띄울 명령. npx 가 없으면 None."""
    npx = shutil.which("npx", path=augmented_path(os.environ.get("PATH")))
    if not npx:
        return None
    chrome = any(Path(p).is_file() for p in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe")) or bool(
        shutil.which("google-chrome") or shutil.which("chrome") or Path("/Applications/Google Chrome.app").exists())
    browser = "chrome" if chrome or not procs.IS_WINDOWS else "msedge"
    return Browser(url=url, command=npx,
                   args=["-y", "@playwright/mcp@latest", "--headless", "--isolated", "--browser", browser])


class AppServer:
    """리뷰 동안 앱을 백그라운드로 띄워 둔다. with 문을 벗어나면 프로세스 트리를 끈다."""

    def __init__(self, workdir: Path, app: WebApp, log_path: Path, *, timeout: float = START_TIMEOUT_SEC):
        self.workdir, self.app, self.log_path, self.timeout = Path(workdir), app, Path(log_path), timeout
        self.proc = None
        self.url: str | None = None
        self.error: str | None = None

    def start(self) -> str | None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.log_path.open("wb") as log:
                self.proc = spawn_detached(self.app.command, self.workdir, log_file=log,
                                           env={"BROWSER": "none", "CI": "1", "PYTHONUNBUFFERED": "1"})
        except (ExecutableNotFound, OSError) as e:
            self.error = f"앱을 띄우지 못함: {e}"
            return None
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                self.error = f"앱이 바로 끝남 (exit {self.proc.returncode}): {self._tail()}"
                return None
            url = self._find_url()
            if url:
                self.url = url
                return url
            time.sleep(0.2)
        self.error = f"{int(self.timeout)}초 안에 앱 주소를 찾지 못함: {self._tail()}"
        self.stop()
        return None

    def _tail(self) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")[-300:].strip()
        except OSError:
            return ""

    def _find_url(self) -> str | None:
        if self.app.kind == "static":
            try:
                with socket.create_connection(("127.0.0.1", self.app.port), timeout=0.5):
                    return f"http://127.0.0.1:{self.app.port}/"
            except OSError:
                return None
        m = _URL_RE.search(self._tail_all())
        if not m:
            return None
        host = "127.0.0.1" if m.group(1) == "0.0.0.0" else m.group(1)
        return f"http://{host}:{m.group(2)}/"

    def _tail_all(self) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            procs.kill_tree(self.proc)
        self.proc = None

    def __enter__(self) -> "AppServer":
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
