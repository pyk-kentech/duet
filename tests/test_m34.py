"""M34: 대화형 터미널 세션 (DESIGN.md 36.19). 진짜 CLI 대신 가짜 대화형 CLI(tests/fake_bin/_fake_interactive.py)."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tenure.agentconfig import MASK, agent_config
from tenure.registry import Registry
from tenure.runner import run_process
from tenure.term import hooks, rules
from tenure.term.session import SessionError, SessionManager
from tenure.ui.server import make_server

TOKEN = "t-m34"


def wait_for(cond, timeout=20.0, step=0.1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = cond()
        if v:
            return v
        time.sleep(step)
    raise AssertionError("시간 안에 조건이 맞지 않음")


@pytest.fixture
def on_path(fake_bin, monkeypatch):
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ["PATH"])
    return fake_bin


# ------------------------------------------------------------------ rules
def test_builtin_rules_and_tail():
    rs = rules.load_rules(None)
    hit = rules.match(rs, "claude", "작업...\r\n\x1b[1mDo you want to proceed?\x1b[0m\r\n❯ 1. Yes\r\n")
    assert hit and hit[0].id == "claude-permission" and hit[0].approve == "\r" and "\x1b" not in hit[1]
    assert rules.match(rs, "codex", "Allow command? rm -rf x")[0].id == "codex-approval"
    assert rules.match(rs, "codex", "Do you want to proceed?") is None          # 다른 에이전트의 규칙은 안 봄
    assert rules.match(rs, "claude", "Continue? (y/n)")[0].id == "generic-yes-no"
    assert rules.tail_lines("a\r\n\r\nb\x1b[2K\r\nc\n", 2) == "b\nc"


def test_user_rules_override_add_disable(tmp_path):
    (tmp_path / rules.RULES_FILE).write_text(
        '[[rules]]\nid = "claude-working"\nenabled = false\n'
        '[[rules]]\nid = "claude-permission"\nregex = "허락할까요"\napprove = "1"\n'
        '[[rules]]\nid = "my-question"\nagent = "*"\nstate = "blocked"\nregex = "질문:"\npriority = 5\ndeny = "\\\\u001b"\n',
        encoding="utf-8")
    rs = rules.load_rules(tmp_path)
    ids = {r.id: r for r in rs}
    assert "claude-working" not in ids and ids["claude-permission"].approve == "1" and ids["claude-permission"].source == "사용자"
    assert ids["my-question"].deny == "\x1b"
    assert rules.match(rs, "claude", "허락할까요")[0].id == "claude-permission"
    (tmp_path / rules.RULES_FILE).write_text('[[rules]]\nid = "x"\nstate = "blocked"\nregex = "("\n', encoding="utf-8")
    with pytest.raises(rules.RuleError, match="정규식"):
        rules.load_rules(tmp_path)


# ------------------------------------------------------------------ hooks
def test_hook_settings_and_record(tmp_path):
    data = json.loads(hooks.claude_settings(tmp_path, "n1"))
    assert set(data["hooks"]) == set(hooks.CLAUDE_EVENTS) and "_hook" in data["hooks"]["Stop"][0]["hooks"][0]["command"]
    import tomllib
    flag, value = hooks.codex_args(tmp_path, "n1")
    assert flag == "-c" and tomllib.loads("x = " + value[len("notify="):])["x"][-1] == hooks.CODEX_EVENT
    hooks.record(tmp_path, "n1", "Notification", json.dumps({"notification_type": "permission_prompt", "message": "권한", "x": 1}))
    hooks.record(tmp_path, "other", "Stop", "{}")
    with (tmp_path / hooks.HOOKS_FILE).open("a", encoding="utf-8") as f:
        f.write('{"nonce": "n1", "event": "Stop"')                          # 쓰는 중인 줄
    evs, off = hooks.read_new(tmp_path, 0, "n1")
    assert [e["event"] for e in evs] == ["Notification"] and "x" not in evs[0]["data"]
    assert hooks.interpret(evs[0]) == ("blocked", "권한")
    assert hooks.interpret({"event": "Stop"})[0] == "idle" and hooks.interpret({"event": "UserPromptSubmit"})[0] == "working"


def test_hook_command_entry_point(tmp_path):
    """`python -m tenure _hook` 은 무거운 cli 없이 바로 쓴다(CLI 가 기다림)."""
    r = run_process([sys.executable, "-m", "tenure", "_hook", str(tmp_path), "n9", "Stop"], cwd=tmp_path,
                    stdin_text='{"hook_event_name": "Stop"}', timeout_sec=30)
    assert r.ok and r.stdout == ""
    evs, _ = hooks.read_new(tmp_path, 0, "n9")
    assert evs[0]["event"] == "Stop" and evs[0]["data"]["hook_event_name"] == "Stop"


# ------------------------------------------------------------------ sessions
def test_claude_session_full_flow(tmp_path, on_path):
    m = SessionManager(tmp_path / "home")
    s = m.create("claude", tmp_path, str(tmp_path), rows=24, cols=100)
    wait_for(lambda: s.status()["source"] == "hook" and s.status()["state"] == "idle")   # SessionStart 훅
    s.send("안녕")
    wait_for(lambda: s.status()["attention"] == "done-unseen")                        # Stop 훅
    m.mark_seen(s.meta.id)
    assert s.status()["attention"] is None
    s.send("권한이 필요한 일")
    st = wait_for(lambda: (x := s.status())["state"] == "blocked" and x)
    assert "permission" in st["reason"] and st["attention"] == "blocked"
    with pytest.raises(SessionError, match="승인을 기다리는"):
        s.send("또")
    assert s.answer(True) == "\r"
    wait_for(lambda: "승인됨" in s.snapshot()["data"])
    wait_for(lambda: s.status()["state"] == "idle")
    e = s.explain()
    assert e["hook"]["event"] == "Stop" and e["rule"] is None                          # 지난 질문은 판단에 안 씀
    s.send("exit")
    wait_for(lambda: s.status()["state"] == "ended")
    wait_for(lambda: s.meta.ended is not None)
    assert "끝" in (s.dir / "output.log").read_text(encoding="utf-8")
    again = SessionManager(tmp_path / "home")                                       # 서버를 다시 켜도 기록으로 보임
    past = again.get(s.meta.id)
    assert not past.live and "권한이 필요한 일" in past.snapshot()["data"]


def test_codex_session_screen_rule_and_notify_chain(tmp_path, on_path, monkeypatch):
    marker = tmp_path / "chained.txt"
    chain = [sys.executable, "-c", f"import sys; open(r'{marker}', 'w', encoding='utf-8').write(sys.argv[-1])"]
    monkeypatch.setattr(hooks, "user_codex_notify", lambda: chain)
    m = SessionManager(tmp_path / "home")
    s = m.create("codex", tmp_path, str(tmp_path))
    wait_for(lambda: "대화형" in s.snapshot()["data"])
    s.send("권한 필요한 명령")
    st = wait_for(lambda: (x := s.status())["state"] == "blocked" and x)
    assert st["source"] == "screen" and st["rule"] == "codex-approval"
    assert s.answer(True) == "y"
    wait_for(lambda: s.status()["attention"] == "done-unseen")                        # notify 훅
    assert "승인됨" in s.snapshot()["data"]
    wait_for(lambda: marker.exists())                                               # 사용자의 원래 notify 도 불림
    assert "agent-turn-complete" in marker.read_text(encoding="utf-8")
    s.kill()
    wait_for(lambda: s.status()["state"] == "ended")


def test_session_errors(tmp_path, on_path):
    m = SessionManager(tmp_path / "home")
    with pytest.raises(SessionError, match="에이전트는"):
        m.create("bash", tmp_path, str(tmp_path))
    with pytest.raises(SessionError):
        m.get("../x")
    # 실행 파일이 없을 때: PATH 를 비우면 흔한 설치 경로에서 진짜 CLI 를 찾을 수 있으므로 없는 경로를 직접 준다
    with pytest.raises(SessionError, match="띄우지 못했습니다"):
        m.create("claude", tmp_path, str(tmp_path), bin=str(tmp_path / "no-such-claude"))


# ------------------------------------------------------------------ server
@pytest.fixture
def server():
    srv = make_server("127.0.0.1", 0, token=TOKEN)
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def api(srv, path, *, method="GET", body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}{path}", data=data, method=method,
                               headers={"X-Tenure-Token": TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def test_session_api(server, tmp_path, on_path):
    proj = tmp_path / "p"
    proj.mkdir()
    Registry().add(proj)
    s, info = api(server, "/api/sessions", method="POST", body={"agent": "claude", "project": str(proj), "rows": 20, "cols": 90})
    assert s == 200 and info["live"] and info["cwd"] == str(proj)
    sid = info["id"]
    wait_for(lambda: "대화형" in api(server, f"/api/session?id={sid}&offset=0")[1]["data"])
    assert api(server, "/api/session/send", method="POST", body={"id": sid, "text": "안녕"})[0] == 200
    wait_for(lambda: api(server, "/api/sessions")[1]["sessions"][0]["status"]["attention"] == "done-unseen")
    snap = api(server, f"/api/session?id={sid}&offset=0")[1]
    tail = api(server, f"/api/session?id={sid}&offset={snap['offset']}")[1]
    assert "완료: 안녕" in snap["data"] and tail["data"] == ""
    assert api(server, "/api/session/resize", method="POST", body={"id": sid, "rows": 30, "cols": 100})[0] == 200
    assert api(server, "/api/session/explain?id=" + sid)[1]["status"]["state"] == "idle"
    assert api(server, "/api/session/input", method="POST", body={"id": sid, "data": "x" * 70_000})[0] == 400
    assert api(server, "/api/session?id=nope")[0] == 404
    assert api(server, "/api/sessions", method="POST", body={"agent": "claude", "project": str(proj), "machine": "lab"})[0] == 400
    assert api(server, "/api/session/close", method="POST", body={"id": sid})[0] == 409                 # 진행 중
    assert api(server, "/api/session/kill", method="POST", body={"id": sid})[0] == 200
    wait_for(lambda: not api(server, "/api/sessions")[1]["sessions"][0]["live"])
    assert api(server, "/api/session/close", method="POST", body={"id": sid})[0] == 200
    assert api(server, "/api/sessions")[1]["sessions"] == []


# ------------------------------------------------------------------ agent config
def test_agent_config_masks_secrets(tmp_path, monkeypatch):
    claude = tmp_path / "claude-config"
    (claude / "skills" / "deploy").mkdir(parents=True)
    (claude / "skills" / "deploy" / "SKILL.md").write_text("---\nname: deploy\ndescription: 배포\n---\n본문", encoding="utf-8")
    (claude / "settings.json").write_text(json.dumps({"env": {"API_KEY": "sk-secretsecretsecret"},
                                                      "permissions": {"allow": ["Bash(git:*)"]}, "model": "opus"}), encoding="utf-8")
    codex = tmp_path / "codex-home"
    codex.mkdir()
    (codex / "config.toml").write_text('model = "gpt-6.1-sol"\napi_key = "sk-xxxxxxxxxxxxxxxx"\n'
                                       '[mcp_servers.gh]\ncommand = "gh-mcp"\nargs = ["--token=ghp_abcdefghijklmnop"]\n'
                                       '[mcp_servers.gh.env]\nGH_TOKEN = "ghp_zzzzzzzzzzzzzzzz"\n', encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    monkeypatch.setenv("CODEX_HOME", str(codex))
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "CLAUDE.md").write_text("# 규칙\n", encoding="utf-8")
    (proj / ".mcp.json").write_text(json.dumps({"mcpServers": {"db": {"command": "db-mcp", "env": {"PASS": "hunter2"}}}}), encoding="utf-8")
    d = agent_config(proj)
    text = json.dumps(d, ensure_ascii=False)
    assert "sk-secret" not in text and "ghp_" not in text and "hunter2" not in text and "api_key" not in text
    c, x = d["claude"], d["codex"]
    assert c["settings"][0]["env"] == ["API_KEY"] and c["settings"][0]["model"] == "opus"
    assert [s["name"] for s in c["skills"]] == ["deploy"] and c["memory"][0]["first_line"] == "규칙"
    assert c["mcp"][0]["name"] == "db" and c["mcp"][0]["env"] == ["PASS"]
    assert x["settings"]["model"] == "gpt-6.1-sol" and x["mcp"][0]["args"] == [f"--{MASK}"] or MASK in x["mcp"][0]["args"][0]
    assert x["mcp"][0]["env"] == ["GH_TOKEN"]
