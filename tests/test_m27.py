"""M27: 권한 수준, 웹 검색, 패키지 버전 조회, 첨부, 브라우저 확인 (DESIGN.md 33장). 실제 CLI 는 부르지 않는다."""

from __future__ import annotations

import base64
import json
import socket
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import duet.orchestrator as orch_mod
from duet import attachments, browser as browserlib
from duet.agents.base import AgentRequest, Mode
from duet.agents.claude_code import ClaudeCodeAdapter
from duet.agents.codex import CodexAdapter
from duet.agents.mock import MockAdapter
from duet.cli import main
from duet.config import Config, ConfigError, load_config
from duet.options import BY_KEY
from duet.phases.build import BuildPhase
from duet.state import RunState, list_run_dirs
from duet.tools import PACKAGE_LOOKUP_TOOLS, Browser
from duet.ui.dashboard import ApiError, Dashboard


def creq(step="propose", mode=Mode.READ, **kw):
    return AgentRequest("p", Path("."), mode, 60, step, **kw)


def claude_cmd(cfg, req):
    return ClaudeCodeAdapter(cfg).build_command(req)[0]


def codex_cmd(cfg, req):
    return CodexAdapter(cfg).build_command(req, Path("last.md"))[0]


def after(cmd, flag):
    return cmd[cmd.index(flag) + 1]


# ====================================================================== 기본값·설정
def test_defaults_and_validation():
    c = Config()
    assert (c.access, c.web_search, c.package_lookup, c.browser_check) == ("full", "on", True, "auto")
    assert {"access", "web_search", "package_lookup", "browser_check"} <= set(BY_KEY)
    for key, bad in (("access", "root"), ("web_search", "maybe"), ("browser_check", "always")):
        with pytest.raises(ConfigError, match=key):
            load_config(None, {key: bad})


# ====================================================================== 33.5 권한 full
def test_claude_full_access():
    c = Config()
    cmd = claude_cmd(c, creq("propose"))
    assert after(cmd, "--permission-mode") == "bypassPermissions" and "--allowedTools" not in cmd
    assert after(cmd, "--disallowedTools") == "Edit,Write,NotebookEdit"       # 읽기 단계는 편집만 뺌, 웹은 씀
    cmd = claude_cmd(c, creq("implement", Mode.WRITE))
    assert after(cmd, "--permission-mode") == "bypassPermissions" and "--disallowedTools" not in cmd
    cmd = claude_cmd(replace(c, web_search="off"), creq("implement", Mode.WRITE))
    assert after(cmd, "--disallowedTools") == "WebSearch,WebFetch"
    assert "WebSearch" in after(claude_cmd(c, creq("dedup")), "--disallowedTools")   # 보조 호출은 웹 없음
    assert "--settings" not in claude_cmd(replace(c, claude_sandbox=True), creq("implement", Mode.WRITE))


def test_codex_full_access_and_search():
    c = Config()
    cmd = codex_cmd(c, creq("review"))
    assert cmd[1] == "--search" and cmd[2] == "exec"                        # 최상위 옵션은 exec 앞
    assert "--dangerously-bypass-approvals-and-sandbox" in cmd and "--sandbox" not in cmd
    cmd = codex_cmd(c, creq("implement", Mode.WRITE))
    assert "--search" in cmd and "--dangerously-bypass-approvals-and-sandbox" in cmd
    assert "--search" not in codex_cmd(c, creq("dedup"))
    assert "--search" not in codex_cmd(replace(c, web_search="off"), creq("review"))
    resumed = codex_cmd(replace(c, codex=replace(c.codex, resume_args=["exec", "resume"])),
                        creq("review", resume_session="s1"))
    assert resumed[1:4] == ["--search", "exec", "resume"] and "--dangerously-bypass-approvals-and-sandbox" in resumed


# ====================================================================== 33.1·33.2 권한 standard
def test_claude_standard_web_and_package_lookup():
    c = Config(access="standard")
    cmd = claude_cmd(c, creq("propose"))
    i = cmd.index("--allowedTools")
    tools = cmd[i + 1:cmd.index("--")]
    assert tools[0] == "Read,Glob,Grep" and "WebSearch" in tools and "WebFetch" in tools
    assert all(t in tools for t in PACKAGE_LOOKUP_TOOLS) and "--permission-mode" not in cmd
    w = claude_cmd(c, creq("implement", Mode.WRITE))
    assert "WebSearch" not in w and after(w, "--permission-mode") == "acceptEdits"   # standard 는 쓰기 단계에 웹 없음
    off = claude_cmd(replace(c, web_search="off", package_lookup=False), creq("propose"))
    assert "WebSearch" not in off and not any("npm view" in a for a in off)


def test_codex_standard():
    c = Config(access="standard")
    r = codex_cmd(c, creq("review"))
    assert "--search" in r and after(r, "--sandbox") == "read-only"
    w = codex_cmd(c, creq("implement", Mode.WRITE))
    assert "--search" not in w and after(w, "--sandbox") == "workspace-write"


# ====================================================================== 33.3 첨부: 인자
def test_codex_images_and_browser_args():
    tool = Browser(url="http://localhost:5173/", command=r"C:\nodejs\npx.cmd", args=["-y", "@playwright/mcp@latest"])
    cmd = codex_cmd(Config(), creq("review", images=["a.png", "b.jpg"], browser=tool))
    assert [cmd[i + 1] for i, a in enumerate(cmd) if a == "-i"] == ["a.png", "b.jpg"]
    cs = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-c"]
    assert 'mcp_servers.playwright.command="C:\\\\nodejs\\\\npx.cmd"' in cs
    assert 'mcp_servers.playwright.args=["-y", "@playwright/mcp@latest"]' in cs
    std = claude_cmd(Config(access="standard"), creq("review", browser=tool))
    assert "mcp__playwright" in std and json.loads(after(std, "--mcp-config"))["mcpServers"]["playwright"]["command"]
    full = claude_cmd(Config(), creq("review", browser=tool))
    assert "--mcp-config" in full


# ====================================================================== 33.3 첨부: 실행
def run_with(tmp_path: Path, monkeypatch, *extra: str):
    seen: dict = {}

    def factory(cfg, *, mock):
        seen["claude"] = MockAdapter(label="claude")
        seen["codex"] = MockAdapter(label="codex")
        return dict(seen)

    monkeypatch.setattr(orch_mod, "make_agents", factory)
    wd = tmp_path / "w"
    rc = main(["run", "메모 CLI", "--workdir", str(wd), "--mock", "--debate-rounds", "0", *extra])
    [rd] = list_run_dirs(wd)
    return rc, seen, RunState.load(rd), rd


def test_attachments_copied_and_shown(tmp_path: Path, monkeypatch):
    (tmp_path / "spec.md").write_text("# 요구\n- 태그 검색", encoding="utf-8")
    (tmp_path / "screen.png").write_bytes(b"\x89PNG fake")
    rc, seen, st, rd = run_with(tmp_path, monkeypatch, "--attach", str(tmp_path / "spec.md"),
                                "--attach", str(tmp_path / "screen.png"), "--attach", str(tmp_path / "spec.md"))
    assert rc == 0 and st.attachments == ["attachments/spec.md", "attachments/screen.png", "attachments/spec-2.md"]
    assert (rd / "attachments" / "screen.png").read_bytes() == b"\x89PNG fake"
    calls = {c.step: c for c in seen["claude"].calls + seen["codex"].calls}
    for step in ("propose", "implement", "review"):
        assert "## 첨부 파일" in calls[step].prompt and ".duet/runs/" in calls[step].prompt
    review = calls["review"]
    assert [Path(p).name for p in review.images] == ["screen.png"]             # 이미지는 -i 용으로도
    assert "첨부 2" not in (rd / "console.log").read_text(encoding="utf-8") and \
        "첨부 3개" in (rd / "console.log").read_text(encoding="utf-8")


def test_attachment_limits(tmp_path: Path, monkeypatch):
    with pytest.raises(attachments.AttachmentError, match="없습니다"):
        attachments.check([tmp_path / "nope.txt"])
    files = []
    for i in range(11):
        p = tmp_path / f"f{i}.txt"
        p.write_text("x", encoding="utf-8")
        files.append(p)
    with pytest.raises(attachments.AttachmentError, match="10개"):
        attachments.check(files)
    monkeypatch.setattr(attachments, "MAX_TOTAL_BYTES", 3)
    with pytest.raises(attachments.AttachmentError, match="MB"):
        attachments.check(files[:5])
    assert attachments.safe_name("../a b/c?d*.png") == "c_d_.png"
    assert main(["run", "t", "--workdir", str(tmp_path / "w"), "--mock", "--attach", str(tmp_path / "nope")]) != 0


def test_dashboard_attachments(tmp_path: Path, monkeypatch):
    seen = {}
    monkeypatch.setattr(Dashboard, "_spawn", lambda self, kind, wd, argv: seen.update(argv=argv) or {"id": "j"})
    data = base64.b64encode(b"hello").decode()
    Dashboard().start_run({"task": "t", "project": str(tmp_path / "p"), "mock": True,
                           "attachments": [{"name": "../evil name.txt", "data": data}, {"name": "x.png", "data": data}]})
    paths = [seen["argv"][i + 1] for i, a in enumerate(seen["argv"]) if a == "--attach"]
    assert [Path(p).name for p in paths] == ["evil name.txt", "x.png"] and all(Path(p).read_bytes() == b"hello" for p in paths)
    assert all(".duet" in p and "attachments" in p for p in paths)
    for bad, msg in (([{"name": "a", "data": "!!notb64"}], "읽을 수 없습니다"), ([{"name": "a", "data": data}] * 11, "10개"),
                     ("x", "10개")):
        with pytest.raises(ApiError, match=msg):
            Dashboard().start_run({"task": "t", "project": str(tmp_path / "q"), "mock": True, "attachments": bad})


# ====================================================================== 최신 정보 안내
def test_prompt_tools_note(tmp_path: Path, monkeypatch):
    rc, seen, st, rd = run_with(tmp_path, monkeypatch)
    calls = {c.step: c.prompt for c in seen["claude"].calls + seen["codex"].calls}
    assert "## 최신 정보" in calls["propose"] and "npm view" in calls["propose"]
    assert "## 최신 정보" in calls["implement"]                                  # full 은 구현에도 웹
    rc, seen, st, rd = run_with(tmp_path / "b", monkeypatch, "--set", "web_search=off", "--set", "access=standard",
                                "--set", "package_lookup=false")
    calls = {c.step: c.prompt for c in seen["claude"].calls + seen["codex"].calls}
    assert "## 최신 정보" not in calls["propose"] and "npm view" not in calls["propose"]


# ====================================================================== 33.4 브라우저 확인
def test_detect_web_app(tmp_path: Path):
    assert browserlib.detect(tmp_path) is None
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}}), encoding="utf-8")
    assert browserlib.detect(tmp_path) is None                                  # node_modules 없으면 못 띄움
    (tmp_path / "node_modules").mkdir()
    app = browserlib.detect(tmp_path)
    assert app.kind == "npm" and app.command == ["npm", "run", "dev"]
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"start": "node s.js"}}), encoding="utf-8")
    assert browserlib.detect(tmp_path).command == ["npm", "start"]
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    app = browserlib.detect(static)
    assert app.kind == "static" and app.port and str(app.port) in app.command


def test_playwright_tool_finds_npx_on_path(tmp_path: Path, monkeypatch):
    # 실제 실행에서 시스템 PATH 를 빼고 찾아 'npx 가 없어'로 건너뛴 회귀
    name = "npx.cmd" if sys.platform == "win32" else "npx"
    fake = tmp_path / name
    fake.write_text("@echo off\n" if sys.platform == "win32" else "#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(browserlib.procs, "extra_bin_dirs", lambda: [])
    tool = browserlib.playwright_tool("http://127.0.0.1:5173/")
    assert tool is not None and Path(tool.command).parent == tmp_path
    assert tool.args[:2] == ["-y", "@playwright/mcp@latest"] and "--headless" in tool.args


@pytest.mark.parametrize("module", ["duet.tools", "duet.browser", "duet.attachments"])
def test_new_modules_import_standalone(module: str):
    # duet.tools 가 duet.agents 를 불러 순환 import 가 나던 회귀: 새 프로세스에서 단독으로 불러 본다
    import subprocess
    proc = subprocess.run([sys.executable, "-c", f"import {module}"], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr


def _closed(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return False
    except OSError:
        return True


def test_app_server_static_and_url_parsing(tmp_path: Path):
    (tmp_path / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    app = browserlib.detect(tmp_path)
    with browserlib.AppServer(tmp_path, app, tmp_path / "log.txt", timeout=20) as srv:
        url = srv.start()
        assert url == f"http://127.0.0.1:{app.port}/"
    assert _closed(app.port)
    port = browserlib._free_port()
    script = ("import http.server, socketserver, sys\n"
              f"print('  Local:   http://localhost:{port}/', flush=True)\n"
              f"socketserver.TCPServer(('127.0.0.1', {port}), http.server.SimpleHTTPRequestHandler).serve_forever()\n")
    fake = browserlib.WebApp("npm", [sys.executable, "-c", script])
    with browserlib.AppServer(tmp_path, fake, tmp_path / "log2.txt", timeout=20) as srv:
        assert srv.start() == f"http://localhost:{port}/"
    assert _closed(port)
    dead = browserlib.WebApp("npm", [sys.executable, "-c", "raise SystemExit(3)"])
    srv = browserlib.AppServer(tmp_path, dead, tmp_path / "log3.txt", timeout=10)
    assert srv.start() is None and "exit 3" in srv.error


def test_review_gets_browser_for_web_project(tmp_path: Path, monkeypatch):
    wd = tmp_path / "w"
    wd.mkdir()
    (wd / "index.html").write_text("<h1>app</h1>", encoding="utf-8")
    monkeypatch.setattr(BuildPhase, "_browser_ok", lambda self: True)
    monkeypatch.setattr(browserlib, "playwright_tool", lambda url: Browser(url=url, command="npx", args=[]))
    seen: dict = {}

    def factory(cfg, *, mock):
        seen["claude"] = MockAdapter(label="claude")
        seen["codex"] = MockAdapter(label="codex")
        return dict(seen)

    monkeypatch.setattr(orch_mod, "make_agents", factory)
    assert main(["run", "웹 앱", "--workdir", str(wd), "--mock", "--debate-rounds", "0"]) == 0
    [rd] = list_run_dirs(wd)
    st = RunState.load(rd)
    reviews = [c for c in seen["codex"].calls if c.step == "review"]
    assert reviews and all(c.browser is not None for c in reviews)
    url = st.browser["1"]["url"]
    assert url in reviews[0].prompt and "브라우저로 확인" in reviews[0].prompt
    assert "mcp__playwright__browser_navigate" in reviews[0].prompt                # 도구 이름을 콕 집어 줌
    assert all(c.browser is None for c in seen["claude"].calls)                # 구현자에게는 안 붙임
    assert _closed(int(url.rsplit(":", 1)[1].strip("/")))                        # 리뷰가 끝나면 앱을 끔


def test_browser_skipped_without_web_app_or_npx(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(BuildPhase, "_browser_ok", lambda self: True)
    monkeypatch.setattr(browserlib, "playwright_tool", lambda url: None)
    wd = tmp_path / "w"
    wd.mkdir()
    (wd / "index.html").write_text("x", encoding="utf-8")
    assert main(["run", "웹 앱", "--workdir", str(wd), "--mock", "--debate-rounds", "0"]) == 0
    st = RunState.load(list_run_dirs(wd)[0])
    assert "npx" in st.browser["1"]["error"]
    assert "브라우저 확인 건너뜀" in (list_run_dirs(wd)[0] / "console.log").read_text(encoding="utf-8")
