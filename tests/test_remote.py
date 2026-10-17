"""원격 머신(가짜 ssh) + 설정·환경 API. 가짜 ssh 는 명령을 로컬에서 다른 HOME 으로 실행한다."""

from __future__ import annotations

import os
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

from duet.remote import Remote, RemoteError, build_pyz
from duet.settings import load_settings
from duet.state import list_run_dirs
from duet.ui.server import make_server
from tests.test_ui import TOKEN, call, wait_for


@pytest.fixture
def remote_env(tmp_path: Path, fake_bin: Path, monkeypatch):
    home = tmp_path / "remote-home"
    monkeypatch.setenv("DUET_SSH", str(fake_bin / "ssh"))
    monkeypatch.setenv("DUET_FAKE_REMOTE_HOME", str(home))
    monkeypatch.setenv("DUET_FAKE_PY_DIR", str(Path(sys.executable).parent))
    return home


@pytest.fixture
def server():
    srv = make_server("127.0.0.1", 0, token=TOKEN)
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    for p in srv.dashboard._popens:
        if p.poll() is None:
            p.kill()
    for t in srv.terms.values():
        t.kill()


# ====================================================================== pyz
def test_pyz_is_deterministic_and_complete(tmp_path: Path):
    data, digest = build_pyz()
    assert build_pyz()[1] == digest
    path = tmp_path / "duet.pyz"
    path.write_bytes(data)
    names = zipfile.ZipFile(path).namelist()
    assert "__main__.py" in names and "duet/cli.py" in names
    assert "duet/templates/review.md" in names and "duet/ui/static/app.js" in names
    assert not any("__pycache__" in n for n in names)
    import subprocess
    r = subprocess.run([sys.executable, str(path), "--version"], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0 and "duet" in r.stdout
    # zip 안에서도 템플릿을 읽을 수 있어야 한다(원격 실행)
    r = subprocess.run([sys.executable, "-c",
                        f"import sys; sys.path.insert(0, {str(path)!r}); from duet.prompts import render; "
                        "print(render('propose', task='T')[:80])"], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert "시니어 엔지니어" in r.stdout


# ====================================================================== Remote 클래스
@pytest.mark.skipif(os.name == "nt", reason="가짜 원격이 POSIX 셸(sh)로 명령을 돌린다. 원격은 Linux·macOS (DESIGN.md 27.1)")
def test_remote_probe_deploy_api(remote_env, tmp_path: Path):
    r = Remote({"id": "lab", "ssh": "me@lab"})
    info = r.probe()
    assert info["reachable"] and info["python"] and info["deployed"] is False
    with pytest.raises(RemoteError, match="배포"):
        r.api("projects")
    r = Remote({"id": "lab", "ssh": "me@lab", "python": info["python"]})
    out = r.deploy()
    assert out["deployed"] and "duet" in out["version"]
    assert (remote_env / ".duet" / "bin" / "duet.pyz").exists()
    assert os.access(remote_env / ".duet" / "bin" / "duet", os.X_OK)
    info = r.probe()
    assert info["deployed"] and info["up_to_date"]
    assert r.api("projects") == {"projects": [], "jobs": []}
    with pytest.raises(RemoteError) as e:
        r.api("runs", {"project": "/nope"})
    assert e.value.status == 404


def test_remote_unreachable(remote_env):
    r = Remote({"id": "x", "ssh": "unreachable-host"})
    info = r.probe()
    assert info["reachable"] is False and "연결" in info["error"] and "ssh-copy-id" in info["hint"]
    with pytest.raises(RemoteError, match="SSH 연결 실패"):
        r.api("projects")


# ====================================================================== 서버: 머신 등록 → 배포 → 원격 실행
@pytest.mark.skipif(os.name == "nt", reason="가짜 원격이 POSIX 셸(sh)로 명령을 돌린다. 원격은 Linux·macOS (DESIGN.md 27.1)")
def test_server_remote_machine_end_to_end(server, remote_env, tmp_path: Path):
    s, body, _ = call(server, "POST", "/api/machines", body={"id": "Bad Id", "ssh": "me@lab"})
    assert s == 400
    s, body, _ = call(server, "POST", "/api/machines", body={
        "id": "lab", "name": "연구실", "ssh": "me@lab", "port": "22", "workspace_root": "~/duet-projects"})
    assert s == 200 and body["settings"]["machines"][0]["id"] == "lab"

    s, info, _ = call(server, "POST", "/api/machines/probe", body={"machine": "lab"})
    assert s == 200 and info["reachable"] and info["python"]
    assert load_settings()["machines"][0]["python"] == info["python"]   # 찾은 Python 을 저장
    s, out, _ = call(server, "POST", "/api/machines/deploy", body={"machine": "lab"})
    assert s == 200 and out["deployed"]

    s, projects, _ = call(server, "GET", "/api/projects")
    groups = {g["id"]: g for g in projects["machines"]}
    assert set(groups) == {"local", "lab"} and groups["lab"]["error"] is None and groups["lab"]["projects"] == []

    # 원격에서 mock 실행
    remote_wd = str(remote_env / "duet-projects" / "memo")
    s, job, _ = call(server, "POST", "/api/actions/run", body={
        "machine": "lab", "project": remote_wd, "task": "원격 메모 CLI", "mock": True, "debate_rounds": 0})
    assert s == 200, job
    j = wait_for(lambda: next((x for x in call(server, "GET", "/api/jobs?machine=lab")[1]["jobs"]
                               if x["id"] == job["id"] and not x["running"]), None))
    assert j["returncode"] == 0, j["log_tail"]

    s, runs, _ = call(server, "GET", f"/api/runs?machine=lab&project={remote_wd}")
    assert s == 200 and runs["runs"][0]["status"] == "done_approved"
    run_id = runs["runs"][0]["run_id"]
    s, run, _ = call(server, "GET", f"/api/run?machine=lab&project={remote_wd}&run={run_id}")
    assert run["entries"][0]["name"] == "01_propose_claude.md"
    s, entry, _ = call(server, "GET", f"/api/entry?machine=lab&project={remote_wd}&run={run_id}&file=03_synthesize_codex.md")
    assert "## 결정 사항" in entry["body"]
    # 기록은 원격 HOME 쪽에만 있다
    assert list_run_dirs(Path(remote_wd)) and (remote_env / ".duet" / "projects.json").exists()
    server._remote_cache.clear()
    s, projects, _ = call(server, "GET", "/api/projects")
    lab = next(g for g in projects["machines"] if g["id"] == "lab")
    assert [p["path"] for p in lab["projects"]] == [remote_wd]
    # 로컬 목록에는 안 섞인다
    assert projects["projects"] == []

    s, body, _ = call(server, "DELETE", "/api/machines?id=lab")
    assert body["settings"]["machines"] == []
    assert call(server, "GET", f"/api/runs?machine=lab&project={remote_wd}")[0] == 404


def test_server_unreachable_machine_shows_error(server, remote_env):
    call(server, "POST", "/api/machines", body={"id": "gone", "ssh": "unreachable-x"})
    s, projects, _ = call(server, "GET", "/api/projects")
    gone = next(g for g in projects["machines"] if g["id"] == "gone")
    assert gone["error"] and "SSH" in gone["error"]
    s, info, _ = call(server, "POST", "/api/machines/probe", body={"machine": "gone"})
    assert info["reachable"] is False


# ====================================================================== 서버: 설정·환경·터미널
def test_settings_api(server):
    s, v, _ = call(server, "GET", "/api/settings")
    assert s == 200 and v["settings"]["workspace_roots"] == [] and "codex" in v["suggestions"]
    assert v["effective"]["implementer"] == "claude"
    s, v, _ = call(server, "POST", "/api/settings", body={
        "workspace_roots": ["~/projects", " "], "defaults": {"debate_rounds": "2", "codex": {"model": "gpt-x", "effort": ""}}})
    assert s == 200 and v["settings"]["workspace_roots"] == ["~/projects"]
    assert v["settings"]["defaults"] == {"debate_rounds": 2, "codex": {"model": "gpt-x"}}
    assert v["effective"]["debate_rounds"] == 2 and v["effective"]["codex"]["model"] == "gpt-x"
    s, err, _ = call(server, "POST", "/api/settings", body={"workspace_roots": ["rel"]})
    assert s == 400
    s, err, _ = call(server, "POST", "/api/settings", body={"defaults": {"max_review": 50}})
    assert s == 400


def test_doctor_api(server, fake_bin, monkeypatch):
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    s, d, _ = call(server, "GET", "/api/doctor")
    assert s == 200 and d["ready"] is True
    assert {c["id"] for c in d["checks"]} >= {"duet", "git", "claude", "codex", "uv"}
    s, a, _ = call(server, "GET", "/api/setup/actions")
    assert "install_claude" in a["actions"] and a["actions"]["login_codex"]["interactive"]


def test_setup_action_terminal_flow(server, monkeypatch):
    import duet.ui.server as srv_mod
    from duet.doctor import Action

    # Windows 는 PowerShell 파이프 방식으로 같은 흐름을 본다 (DESIGN.md 27.5)
    test_action = Action("t", "테스트 로그인", "printf 'code? '; read x; echo \"ok:$x\"", True,
                         windows="Write-Host -NoNewline 'code? '; $x = [Console]::In.ReadLine(); Write-Output ('ok:' + $x)",
                         win_interactive=False)
    monkeypatch.setattr(srv_mod, "action_shell", lambda aid: test_action if aid == "t" else (_ for _ in ()).throw(KeyError(aid)))
    assert call(server, "POST", "/api/setup/action", body={"action": "rm -rf /"})[0] == 400
    s, job, _ = call(server, "POST", "/api/setup/action", body={"action": "t"})
    assert s == 200 and job["running"]
    assert call(server, "POST", "/api/setup/action", body={"action": "t"})[0] == 409   # 같은 동작 중복 실행 방지
    wait_for(lambda: "code?" in call(server, "GET", f"/api/term?id={job['id']}")[1]["text"])
    assert call(server, "POST", "/api/term/input", body={"id": job["id"], "text": "XYZ"})[0] == 200
    snap = wait_for(lambda: (lambda t: t if not t["running"] else None)(call(server, "GET", f"/api/term?id={job['id']}")[1]))
    assert snap["returncode"] == 0 and "ok:XYZ" in snap["text"]
    assert call(server, "POST", "/api/term/input", body={"id": job["id"], "text": "late"})[0] == 409
    assert call(server, "GET", "/api/term?id=nope")[0] == 404
    terms = call(server, "GET", "/api/terms")[1]["terms"]
    assert terms[0]["id"] == job["id"] and terms[0]["returncode"] == 0


def test_usage_api(server, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no-codex"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-claude"))
    from duet.cli import main
    main(["run", "t", "--workdir", str(tmp_path / "p"), "--mock", "--debate-rounds", "0"])
    s, u, _ = call(server, "GET", "/api/usage")
    assert s == 200 and u["codex_limits"] is None
    assert u["claude_local"]["windows"]["5시간"]["output_tokens"] == 0
    assert "projects" in u["duet"]
