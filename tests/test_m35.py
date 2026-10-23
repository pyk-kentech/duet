"""M35: 데스크톱 앱 — 얼린 엔진에서도 자기 자신을 부를 수 있는지, 셸이 읽는 준비 신호, 부모 감시 (DESIGN.md 36.20)."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import tomllib
from pathlib import Path

from tenure import selfcmd
from tenure.entry import run
from tenure.term import hooks

ROOT = Path(__file__).resolve().parent.parent


def test_self_argv_normal_and_frozen(monkeypatch):
    assert selfcmd.self_argv("ui")[-3:] == ["-m", "tenure", "ui"] or selfcmd.self_argv("ui")[-1] == "ui"
    monkeypatch.setattr(selfcmd, "FROZEN", True)
    assert selfcmd.self_argv("_hook", "x") == [sys.executable, "_hook", "x"]
    cmd = hooks._cmd(Path("C:/s"), "n1")                         # 세션 훅도 얼린 엔진을 그대로 부른다
    assert cmd[1:] == ["_hook", "C:/s", "n1"]
    from tenure.ui.dashboard import self_command
    assert self_command() == [sys.executable]


def test_browser_static_server_uses_self(tmp_path, monkeypatch):
    from tenure import browser
    (tmp_path / "index.html").write_text("<h1>x</h1>", encoding="utf-8")
    monkeypatch.setattr(selfcmd, "FROZEN", True)
    app = browser.detect(tmp_path)
    assert app.kind == "static" and app.command[:3] == [sys.executable, "_http", str(app.port)]


def test_entry_hook_fast_path(tmp_path, monkeypatch):
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"hook_event_name": "Stop"}'))
    assert run(["_hook", str(tmp_path), "n2", "Stop"]) == 0
    evs, _ = hooks.read_new(tmp_path, 0, "n2")
    assert evs[0]["event"] == "Stop"


def test_pyz_entry_uses_entry_run():
    import io
    import zipfile
    from tenure.remote import build_pyz
    data, _ = build_pyz()
    main = zipfile.ZipFile(io.BytesIO(data)).read("__main__.py").decode()
    assert "tenure.entry" in main and "tenure/entry.py" in zipfile.ZipFile(io.BytesIO(data)).namelist()


def test_ui_ready_line_and_parent_watch(tmp_path):
    """셸이 읽는 준비 신호, 그리고 부모(셸)가 끝나면 엔진도 끝난다."""
    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(6)"])
    env = {**__import__("os").environ, "TENURE_HOME": str(tmp_path)}
    p = subprocess.Popen([sys.executable, "-m", "tenure", "ui", "--no-browser", "--port", "0", "--ready-line",
                          "--parent-pid", str(parent.pid)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", env=env)
    try:
        ready = None
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            line = p.stdout.readline()
            if line.startswith("TENURE_READY "):
                ready = json.loads(line[len("TENURE_READY "):])
                break
            if not line and p.poll() is not None:
                break
        assert ready and ready["url"].startswith("http://127.0.0.1:") and "?t=" in ready["url"] and isinstance(ready["pid"], int)   # venv python 은 런처라 pid 가 다를 수 있다
        parent.wait(20)
        assert p.wait(30) is not None                               # 부모가 끝나 엔진도 끝남
    finally:
        if p.poll() is None:
            p.kill()
        if parent.poll() is None:
            parent.kill()


def test_desktop_build_wiring():
    """설치 파일은 오르카 포크가 만들고, 얼린 엔진은 build/desktop/dist/tenure-engine 에서 resources/engine 으로 들어간다 (36.23)."""
    src = (ROOT / "desktop" / "build_engine.py").read_text(encoding="utf-8")
    assert 'TARGET = DIST / "tenure-engine"' in src and "src-tauri" not in src
    builder = ROOT / "orca" / "config" / "electron-builder.config.cjs"
    if builder.is_file():                                   # 포크는 따로 저장소라 없는 체크아웃도 있다
        text = builder.read_text(encoding="utf-8")
        assert "'tenure-engine'" in text and "to: 'engine'" in text and "productName: 'tenure'" in text
