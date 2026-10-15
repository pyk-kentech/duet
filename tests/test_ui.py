"""관리자 UI 서버 테스트. 실제 HTTP 서버를 임시 포트로 띄워 요청한다. 실제 claude/codex 는 쓰지 않는다(mock)."""

from __future__ import annotations

import datetime as dt
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from duet.cli import main
from duet.lock import read_lock
from duet.registry import Registry
from duet.state import DONE_APPROVED, DONE_UNAPPROVED, STOPPED_USER, RunState, list_run_dirs
from duet.ui.dashboard import current_call
from duet.ui.server import make_server

TOKEN = "test-token-123"


@pytest.fixture
def server():
    srv = make_server("127.0.0.1", 0, token=TOKEN)
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    # UI 가 띄운 작업이 남지 않게
    for popen in srv.dashboard._popens:
        if popen.poll() is None:
            popen.kill()
            popen.wait()
    for t in srv.terms.values():
        t.kill()


def call(srv, method, path, *, body=None, token=TOKEN, host=None, ctype="application/json", raw=False):
    url = f"http://127.0.0.1:{srv.port}{path}"
    data = None
    headers = {}
    if token is not None:
        headers["X-Duet-Token"] = token
    if host is not None:
        headers["Host"] = host
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        headers["Content-Type"] = ctype
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            content = r.read()
            return r.status, (content if raw else json.loads(content)), dict(r.headers)
    except urllib.error.HTTPError as e:
        content = e.read()
        try:
            parsed = json.loads(content)
        except ValueError:
            parsed = content.decode("utf-8", "replace")
        return e.code, parsed, dict(e.headers)


def wait_for(pred, timeout=30.0, step=0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        v = pred()
        if v:
            return v
        time.sleep(step)
    raise AssertionError("시간 안에 조건이 만족되지 않음")


def mock_run(wd: Path, *extra: str) -> Path:
    assert main(["run", "메모 CLI", "--workdir", str(wd), "--mock", "--debate-rounds", "1", *extra]) in (0, 1)
    return list_run_dirs(wd)[-1]


# ====================================================================== 보안
def test_index_requires_token_and_sets_security_headers(server):
    s, body, _ = call(server, "GET", "/", token=None, raw=True)
    assert s == 403 and "접속 주소" in body
    s, body, headers = call(server, "GET", f"/?t={TOKEN}", token=None, raw=True)
    assert s == 200
    html = body.decode()
    assert f'content="{TOKEN}"' in html and "__DUET_TOKEN__" not in html
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert headers["X-Frame-Options"] == "DENY" and headers["Cache-Control"] == "no-store"
    assert "<script>" not in html  # 인라인 스크립트 없음


def test_static_whitelist(server):
    s, body, headers = call(server, "GET", "/static/app.js", token=None, raw=True)
    assert s == 200 and headers["Content-Type"].startswith("text/javascript") and b"markdown" in body
    assert call(server, "GET", "/static/style.css", token=None, raw=True)[0] == 200
    assert call(server, "GET", "/static/../dashboard.py", token=None, raw=True)[0] == 404
    assert call(server, "GET", "/static/index.html", token=None, raw=True)[0] == 404


def test_api_requires_token(server):
    assert call(server, "GET", "/api/projects", token=None)[0] == 401
    assert call(server, "GET", "/api/projects", token="wrong")[0] == 401
    assert call(server, "GET", "/api/projects")[0] == 200


def test_host_header_checked_against_dns_rebinding(server):
    assert call(server, "GET", "/api/projects", host="evil.example:80")[0] == 403
    assert call(server, "GET", f"/?t={TOKEN}", host="evil.example", raw=True)[0] == 403
    assert call(server, "GET", "/api/projects", host=f"localhost:{server.port}")[0] == 200


def test_post_requires_json(server):
    s, body, _ = call(server, "POST", "/api/projects", body=b"path=/tmp", ctype="application/x-www-form-urlencoded")
    assert s == 415


def test_unknown_api(server):
    assert call(server, "GET", "/api/nope")[0] == 404


# ====================================================================== 프로젝트
def test_add_and_remove_project(server, tmp_path: Path):
    assert call(server, "POST", "/api/projects", body={"path": "relative/dir"})[0] == 400
    assert call(server, "POST", "/api/projects", body={"path": str(Path.home())})[0] == 400
    s, body, _ = call(server, "POST", "/api/projects", body={"path": str(tmp_path / "p1")})
    assert s == 200 and body["path"] == str((tmp_path / "p1").resolve())
    s, body, _ = call(server, "GET", "/api/projects")
    [p] = body["projects"]
    assert p["path"] == str((tmp_path / "p1").resolve()) and p["exists"] is False and p["latest"] is None
    s, body, _ = call(server, "DELETE", f"/api/projects?project={p['path']}")
    assert s == 200
    assert call(server, "GET", "/api/projects")[1]["projects"] == []
    assert call(server, "DELETE", f"/api/projects?project={p['path']}")[0] == 404


def test_cli_run_registers_project(server, tmp_path: Path):
    wd = tmp_path / "memo"
    mock_run(wd)
    s, body, _ = call(server, "GET", "/api/projects")
    [p] = body["projects"]
    assert p["path"] == str(wd.resolve()) and p["run_count"] == 1
    assert p["latest"]["status"] == DONE_APPROVED and p["live"] is None


# ====================================================================== 조회
def test_run_detail_entries_console_design(server, tmp_path: Path):
    wd = tmp_path / "memo"
    rd = mock_run(wd)
    q = f"project={wd.resolve()}&run={rd.name}"
    s, runs, _ = call(server, "GET", f"/api/runs?project={wd.resolve()}")
    assert s == 200 and runs["runs"][0]["run_id"] == rd.name and runs["has_design"] is True
    assert runs["defaults"]["implementer"] == "claude"

    s, run, _ = call(server, "GET", f"/api/run?{q}")
    assert s == 200 and run["state"]["status"] == DONE_APPROVED and run["live"] is False and run["stale"] is False
    names = [e["name"] for e in run["entries"]]
    assert names[0] == "01_propose_claude.md" and names[-1] == "09_review2_codex.md"
    reviews = [e for e in run["entries"] if e["meta"]["step"] == "review"]
    assert [r["verdict"]["status"] for r in reviews] == ["CHANGES_REQUESTED", "APPROVED"]
    assert run["resume"]["possible"] is False and run["current_call"] is None

    s, entry, _ = call(server, "GET", f"/api/entry?{q}&file=05_synthesize_codex.md")
    assert s == 200 and "## 결정 사항" in entry["body"] and entry["meta"]["agent"] == "codex"
    assert "<!-- duet" not in entry["body"]

    s, con, _ = call(server, "GET", f"/api/console?{q}")
    assert "실행 시작" in con["text"] and con["offset"] == con["size"] > 0
    s, con2, _ = call(server, "GET", f"/api/console?{q}&offset={con['offset']}")
    assert con2["text"] == ""

    s, design, _ = call(server, "GET", f"/api/design?project={wd.resolve()}")
    assert "## 결정 사항" in design["text"]


@pytest.mark.parametrize("query,status", [
    ("run=../../etc&file=x", 400),
    ("run=20990101-000000&file=x", 404),
    ("file=../run.json", 404),
    ("file=run.json", 404),
    ("file=01_propose_claude.md/../../run.json", 404),
])
def test_path_traversal_rejected(server, tmp_path: Path, query, status):
    wd = tmp_path / "memo"
    rd = mock_run(wd, "--design-only")
    base = f"project={wd.resolve()}"
    if "run=" not in query:
        base += f"&run={rd.name}"
    assert call(server, "GET", f"/api/entry?{base}&{query}")[0] == status


def test_unregistered_project_rejected(server, tmp_path: Path):
    other = tmp_path / "other"
    mock_run(other, "--design-only")
    Registry().remove(other)
    assert call(server, "GET", f"/api/runs?project={other.resolve()}")[0] == 404
    assert call(server, "GET", "/api/runs?project=/etc")[0] == 404


def test_commits_and_diff(server, tmp_path: Path):
    wd = tmp_path / "memo"
    rd = mock_run(wd)
    q = f"project={wd.resolve()}&run={rd.name}"
    s, c, _ = call(server, "GET", f"/api/commits?{q}")
    assert [x["subject"] for x in c["commits"]] == ["duet: design", "duet: impl round 1", "duet: impl round 2"]
    s, d, _ = call(server, "GET", f"/api/diff?{q}")
    assert d["text"].startswith("[변경 파일 요약]") and "main.py" in d["text"]
    assert "DESIGN.md" not in d["text"] and d["truncated"] is False
    sha = c["commits"][1]["sha"]
    s, d, _ = call(server, "GET", f"/api/diff?{q}&commit={sha}")
    assert s == 200 and "impl round 1" in d["text"]
    assert call(server, "GET", f"/api/diff?{q}&commit=HEAD~1")[0] == 400
    assert call(server, "GET", f"/api/diff?{q}&commit={'0' * 40}")[0] == 404


def test_design_only_run_has_no_commits(server, tmp_path: Path):
    wd = tmp_path / "memo"
    rd = mock_run(wd, "--design-only")
    q = f"project={wd.resolve()}&run={rd.name}"
    assert call(server, "GET", f"/api/commits?{q}")[1] == {"base": None, "commits": []}
    assert call(server, "GET", f"/api/diff?{q}")[1]["text"] == ""


# ====================================================================== 실행 제어
def _job(server, job_id):
    return next(j for j in call(server, "GET", "/api/jobs")[1]["jobs"] if j["id"] == job_id)


def test_start_run_validation(server, tmp_path: Path):
    ok = {"project": str(tmp_path / "x"), "task": "t", "mock": True}
    cases = [
        ({**ok, "project": "rel/x"}, "절대 경로"),
        ({**ok, "task": "  "}, "과제"),
        ({**ok, "implementer": "codex", "reviewer": "codex"}, "달라야"),
        ({**ok, "debate_rounds": 9}, "debate_rounds"),
        ({**ok, "implementer": "gpt"}, "implementer"),
        ({**ok, "skip_design": True}, "DESIGN.md"),
        ({**ok, "skip_design": True, "design_only": True}, "함께"),
        ({**ok, "project": str(Path.home())}, "홈 디렉터리"),
    ]
    for body, msg in cases:
        s, r, _ = call(server, "POST", "/api/actions/run", body=body)
        assert s == 400 and msg in r["error"], (body, r)
    assert not (tmp_path / "x").exists()  # 검증 실패 시 폴더를 만들지 않음


def test_start_run_mock_end_to_end(server, tmp_path: Path):
    wd = tmp_path / "new-proj"
    s, job, _ = call(server, "POST", "/api/actions/run", body={
        "project": str(wd), "task": "할일 CLI\n여러 줄 과제", "mock": True, "debate_rounds": 0, "max_review": 2})
    assert s == 200 and job["kind"] == "run" and job["running"] in (True, False)
    j = wait_for(lambda: (lambda x: x if not x["running"] else None)(_job(server, job["id"])))
    assert j["returncode"] == 0, j["log_tail"]
    st = RunState.load(list_run_dirs(wd)[-1])
    assert st.status == DONE_APPROVED and st.task == "할일 CLI\n여러 줄 과제" and st.config["max_review"] == 2
    assert Registry().contains(wd)
    # 과제 파일과 작업 로그가 .duet/ui 아래에 있고 git 에는 안 들어감
    assert list((wd / ".duet" / "ui" / "tasks").glob("*.md"))
    assert ".duet/" in (wd / ".gitignore").read_text(encoding="utf-8")


def test_stop_then_resume_via_ui(server, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DUET_MOCK_DELAY", "0.6")
    wd = tmp_path / "slow"
    s, job, _ = call(server, "POST", "/api/actions/run", body={
        "project": str(wd), "task": "t", "mock": True, "debate_rounds": 1})
    assert s == 200
    info = wait_for(lambda: (lambda i: i if i and i.run_id else None)(read_lock(wd)))
    project = str(wd.resolve())

    # 실행 중 상세: live, current_call
    run = wait_for(lambda: (lambda r: r if r["current_call"] else None)(
        call(server, "GET", f"/api/run?project={project}&run={info.run_id}")[1]))
    assert run["live"] is True and run["live_pid"] == info.pid
    assert run["current_call"]["agent"] in ("claude", "codex")
    assert run["resume"]["possible"] is False

    # 실행 중에는 새 실행/이어하기를 막음
    assert call(server, "POST", "/api/actions/run", body={"project": str(wd), "task": "t", "mock": True})[0] == 409
    assert call(server, "POST", "/api/actions/resume", body={"project": project, "run": info.run_id})[0] in (400, 409)

    s, r, _ = call(server, "POST", "/api/actions/stop", body={"project": project})
    assert s == 200 and r["stopped"] == info.pid
    j = wait_for(lambda: (lambda x: x if not x["running"] else None)(_job(server, job["id"])))
    assert j["returncode"] == 130, j["log_tail"]
    st = RunState.load(list_run_dirs(wd)[-1])
    assert st.status == STOPPED_USER
    assert call(server, "POST", "/api/actions/stop", body={"project": project})[0] == 409

    monkeypatch.setenv("DUET_MOCK_DELAY", "0")
    s, job2, _ = call(server, "POST", "/api/actions/resume", body={"project": project, "run": info.run_id})
    assert s == 200 and job2["kind"] == "resume"
    j2 = wait_for(lambda: (lambda x: x if not x["running"] else None)(_job(server, job2["id"])))
    assert j2["returncode"] == 0, j2["log_tail"]
    assert RunState.load(list_run_dirs(wd)[-1]).status == DONE_APPROVED
    assert len(list_run_dirs(wd)) == 1


def test_resume_rules_via_ui(server, tmp_path: Path):
    wd = tmp_path / "memo"
    rd = mock_run(wd, "--max-review", "1", "--implementer", "codex", "--reviewer", "claude")
    # mock reviewer 는 2번째 리뷰에서 승인 → max_review 1 이면 미승인
    st = RunState.load(rd)
    assert st.status == DONE_UNAPPROVED
    project = str(wd.resolve())
    s, run, _ = call(server, "GET", f"/api/run?project={project}&run={rd.name}")
    assert run["resume"] == {"possible": True, "needs_max_review": True, "current_max_review": 1, "reason": ""}
    for mr, ok in ((None, False), (1, False), (11, False), ("x", False)):
        s, r, _ = call(server, "POST", "/api/actions/resume", body={"project": project, "run": rd.name, "max_review": mr})
        assert s == 400, (mr, r)
    # resume 한 프로세스의 mock 리뷰어는 횟수를 새로 센다(2번째 리뷰에서 승인) → 3회차에서 승인
    s, job, _ = call(server, "POST", "/api/actions/resume", body={"project": project, "run": rd.name, "max_review": 3})
    assert s == 200
    j = wait_for(lambda: (lambda x: x if not x["running"] else None)(_job(server, job["id"])))
    assert j["returncode"] == 0, j["log_tail"]
    assert RunState.load(rd).status == DONE_APPROVED
    s, r, _ = call(server, "POST", "/api/actions/resume", body={"project": project, "run": rd.name, "max_review": 5})
    assert s == 400 and "끝난" in r["error"]


def test_stale_running_state_reported(server, tmp_path: Path):
    wd = tmp_path / "memo"
    rd = mock_run(wd, "--design-only")
    st = RunState.load(rd)
    st.status = "running"
    st.save(rd)
    s, run, _ = call(server, "GET", f"/api/run?project={wd.resolve()}&run={rd.name}")
    assert run["stale"] is True and run["live"] is False and run["resume"]["possible"] is True


# ====================================================================== current_call
def test_current_call_parsing(tmp_path: Path):
    log = tmp_path / "console.log"
    log.write_text(
        "[10:00:00] 실행 시작: x\n"
        "[10:00:01] claude ← propose 실행 중...\n"
        "[10:00:40] claude ← propose 완료 (39초) → 01_propose_claude.md\n"
        "[10:00:40] codex ← review (재시도 1) 실행 중...\n", encoding="utf-8")
    now = dt.datetime(2026, 10, 15, 10, 2, 0)
    assert current_call(log, now) == {"agent": "codex", "step": "review", "retry": 1, "started": "10:00:40", "elapsed_sec": 80}
    log.write_text(log.read_text(encoding="utf-8") + "[10:03:00] codex ← review 실패: 시간 초과 → x\n", encoding="utf-8")
    assert current_call(log, now) is None
    # 자정 넘김
    log.write_text("[23:59:30] claude ← fix 실행 중...\n", encoding="utf-8")
    assert current_call(log, dt.datetime(2026, 10, 16, 0, 0, 30))["elapsed_sec"] == 60
    assert current_call(tmp_path / "nope.log") is None


# ====================================================================== UI 서버 업데이트·다시 시작
def test_server_info_and_restart(server):
    s, info, _ = call(server, "GET", "/api/server")
    assert s == 200 and info["stale"] is False and info["loaded"] == info["current"] and info["version"]
    server.loaded_hash = "0" * 64           # 코드가 바뀐 것처럼
    assert call(server, "GET", "/api/server")[1]["stale"] is True
    called = []
    server.restart_fn = lambda srv: called.append(srv.port)
    s, r, _ = call(server, "POST", "/api/server/restart", body={})
    assert s == 200 and r == {"restarting": True}
    wait_for(lambda: called == [server.port])


def test_restart_refused_while_terminal_job_runs(server):
    from duet.ui.terminal import TermJob
    job = TermJob(id="t", title="Claude 로그인", argv=["sh", "-c", "sleep 30"]).start()
    server.terms["t"] = job
    server.restart_fn = lambda srv: (_ for _ in ()).throw(AssertionError("다시 시작하면 안 됨"))
    s, r, _ = call(server, "POST", "/api/server/restart", body={})
    assert s == 409 and "Claude 로그인" in r["error"]
    assert call(server, "GET", "/api/server")[1]["running_terms"] == ["Claude 로그인"]


def test_serve_reuses_token_and_port_after_restart(monkeypatch, tmp_path):
    import duet.ui.server as srv_mod
    seen = {}

    class Fake:
        loopback = True
        def url(self): return "http://x"
        def serve_forever(self, poll_interval): raise KeyboardInterrupt
        def server_close(self): pass

    def fake_make(host, port, *, dashboard=None, token=None, port_tries=20):
        seen.update(token=token, port=port, tries=port_tries)
        return Fake()

    monkeypatch.setattr(srv_mod, "make_server", fake_make)
    monkeypatch.setenv("DUET_UI_TOKEN", "keep-me")
    monkeypatch.setenv("DUET_UI_EXACT_PORT", "1")
    srv_mod.serve("127.0.0.1", 8799, open_browser=False, printer=lambda line: None)
    assert seen == {"token": "keep-me", "port": 8799, "tries": 1}
    import os
    assert "DUET_UI_TOKEN" not in os.environ   # 자식 프로세스로 새지 않게 지움


def test_post_without_body_is_accepted(server):
    """본문 없는 POST(예: 다시 시작 버튼)는 Content-Type 없이도 받는다. 본문이 있으면 JSON 이어야 한다."""
    server.restart_fn = lambda srv: None
    url = f"http://127.0.0.1:{server.port}/api/server/restart"
    req = urllib.request.Request(url, data=b"", method="POST", headers={"X-Duet-Token": TOKEN})
    with urllib.request.urlopen(req, timeout=10) as r:
        assert r.status == 200
