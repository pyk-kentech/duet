"""M22: 관리자 UI 개편 (DESIGN.md 28장) — HTTP·데이터 수준. 화면은 헤드리스 브라우저로 따로 확인한다."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from dataclasses import fields
from pathlib import Path

import pytest

import duet.orchestrator as orch_mod
from duet import limits, options
from duet.agents.claude_code import claude_rate_limits, load_claude_limits, parse_stream, save_claude_limits
from duet.agents.mock import MockAdapter
from duet.bench import known_result_dirs, run_bench, workflow_stats
from duet.cli import main
from duet.config import Config, load_config
from duet.registry import Registry
from duet.state import RunState, list_run_dirs
from duet.ui.dashboard import Dashboard, bench_root_of
from duet.ui.server import COOKIE_PREFIX, make_server, saved_token

TOKEN = "m22-token-123456789012345"


@pytest.fixture
def server():
    srv = make_server("127.0.0.1", 0, token=TOKEN)
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def req(srv, path, *, method="GET", headers=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    h = dict(headers or {})
    if data is not None:
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(f"http://127.0.0.1:{srv.port}{path}", data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def api(srv, path, *, method="GET", body=None):
    s, _, raw = req(srv, path, method=method, headers={"X-Duet-Token": TOKEN}, body=body)
    return s, json.loads(raw or b"null")


# ====================================================================== 28.1 접속
def test_cookie_opens_page_but_not_api(server):
    s, h, _ = req(server, f"/?t={TOKEN}")
    cookie = h.get("Set-Cookie", "")
    name = f"{COOKIE_PREFIX}{server.port}"
    assert s == 200 and cookie.startswith(f"{name}={TOKEN}") and "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert req(server, "/", headers={"Cookie": f"{name}={TOKEN}"})[0] == 200          # ?t= 없이 쿠키로
    assert req(server, "/", headers={"Cookie": f"{name}=wrong"})[0] == 403
    assert req(server, "/", headers={"Cookie": f"{COOKIE_PREFIX}1={TOKEN}"})[0] == 403   # 다른 포트의 쿠키
    assert req(server, "/")[0] == 403
    s, _, _ = req(server, "/api/projects", headers={"Cookie": f"{name}={TOKEN}"})      # API 는 쿠키로 안 열림
    assert s == 401


def test_saved_token_persists(isolated_duet_home):
    a = saved_token()
    assert saved_token() == a and len(a) >= 24
    assert (isolated_duet_home / "ui-token").read_text().strip() == a
    b = saved_token(new=True)
    assert b != a and saved_token() == b


# ====================================================================== 28.2 목록
def make_bench_layout(root: Path) -> Path:
    res = root / "bench-out" / "20261017-000000"
    wd = res / "ledger" / "lean-1"
    wd.mkdir(parents=True)
    (res / "results.json").write_text(json.dumps({"meta": {"suite": "hard", "workflows": ["lean"], "tasks": ["ledger"],
                                                            "repeat": 1, "started": "2026-10-17T00:00:00"},
                                                   "rows": []}), encoding="utf-8")
    return wd


def test_projects_bench_display_and_prune(tmp_path: Path):
    reg = Registry()
    a = tmp_path / "x" / "app"
    b = tmp_path / "y" / "app"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    gone = tmp_path / "gone"
    gone.mkdir()
    bench_wd = make_bench_layout(tmp_path)
    for p in (a, b, gone, bench_wd):
        reg.add(p)
    gone.rmdir()
    d = Dashboard()
    by = {Path(p["path"]).name if p["name"] != "app" else p["display"]: p for p in d.projects()}
    assert by["x / app"]["display"] == "x / app" and by["y / app"]["display"] == "y / app"   # 같은 이름은 부모로 구별
    assert by["lean-1"]["bench"] and by["lean-1"]["bench_root"] == str(bench_wd.parent.parent)
    assert not by["gone"]["exists"] and not by["x / app"]["bench"]
    r = d.prune_projects()
    assert r["removed"] == [str(gone.resolve())] and len(reg.list()) == 3
    assert bench_root_of(a) is None


def test_bench_runs_not_registered_and_bench_api(tmp_path: Path, server):
    out = run_bench(task_names=["roman"], out_root=tmp_path / "bench", mock=True, printer=lambda s: None)
    assert Registry().list() == []                                    # 벤치마크 실행은 등록하지 않는다
    assert out in known_result_dirs()                                 # --out 도 index 로 찾는다
    s, lst = api(server, "/api/bench")
    assert s == 200 and lst["results"][0]["dir"] == str(out) and lst["results"][0]["runs"] == 1
    s, res = api(server, f"/api/bench/result?dir={urllib.request.quote(str(out))}")
    assert s == 200 and res["stats"][0]["workflow"] == "classic" and res["rows"][0]["has_runs"]
    assert api(server, "/api/bench/result?dir=/etc")[0] == 404
    row = res["rows"][0]                                              # 등록 안 된 벤치마크 실행도 상세를 연다
    run_id = Path(row["run_dir"]).name
    s, run = api(server, f"/api/run?project={urllib.request.quote(row['workdir'])}&run={run_id}")
    assert s == 200 and run["state"]["run_id"] == run_id


def test_workflow_stats_matches_summary():
    rows = [{"workflow": "lean", "approved": True, "rounds": 1, "seconds": 100, "limit_wait_sec": 40, "calls": 3,
             "hidden": {"passed": 9, "total": 10, "all_passed": False}, "usage": {"claude": {"input": 10, "output": 5}}},
            {"workflow": "lean", "approved": False, "rounds": 3, "seconds": 60, "calls": 7, "arbiter": None,
             "hidden": {"passed": 10, "total": 10, "all_passed": True}, "usage": {}}]
    [s] = workflow_stats(rows)
    assert (s["runs"], s["approved"], s["missed"], s["all_passed"], s["graded"]) == (2, 1, 1, 1, 2)
    assert s["hidden_rate"] == 95 and s["rounds"] == 2 and s["seconds"] == 60


# ====================================================================== 28.4 설정 항목 정의
def test_every_config_field_is_somewhere():
    covered = set(options.BY_KEY) | set(options.BASIC_KEYS) | set(options.NOT_IN_UI)
    missing = [f.name for f in fields(Config) if f.name not in covered]
    assert missing == [], f"UI 에 빠진 설정: {missing}"
    for o in options.OPTIONS:
        assert o.group in options.GROUPS and o.kind in ("bool", "int", "choice", "text")
        assert hasattr(Config(), o.key)


def test_option_parse():
    assert options.parse("arbiter", "false") is False and options.parse("arbiter", True) is True
    assert options.parse("arbiter", "") is None
    assert options.parse("limit_wait_max_min", "120") == 120
    with pytest.raises(options.OptionError):
        options.parse("limit_wait_max_min", "0")
    with pytest.raises(options.OptionError):
        options.parse("review_session", "maybe")
    with pytest.raises(options.OptionError):
        options.parse("no_such", "1")
    assert options.parse_assignments(["arbiter=false", "dedup_model=claude-haiku-5-5"]) == \
        {"arbiter": False, "dedup_model": "claude-haiku-5-5"}
    with pytest.raises(options.OptionError):
        options.parse_assignments(["arbiter"])


def test_cli_set(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(orch_mod, "make_agents", lambda cfg, *, mock: {"claude": MockAdapter(label="claude"),
                                                                       "codex": MockAdapter(label="codex")})
    wd = tmp_path / "w"
    rc = main(["run", "t", "--workdir", str(wd), "--mock", "--debate-rounds", "0", "--design-only",
               "--set", "arbiter=false", "--set", "limit_wait_max_min=90", "--set", "wait_on_limit=true",
               "--wait-on-limit"])
    st = RunState.load(list_run_dirs(wd)[0])
    assert rc == 0 and st.config["arbiter"] is False and st.config["limit_wait_max_min"] == 90 and st.config["wait_on_limit"]
    assert main(["run", "t", "--workdir", str(tmp_path / "w2"), "--mock", "--set", "nope=1"]) == 2


def test_settings_options_save(server):
    s, v = api(server, "/api/settings")
    assert s == 200 and any(o["key"] == "dedup" for o in v["options"])
    s, v = api(server, "/api/settings", method="POST", body={"options": {"arbiter": "false", "limit_wait_max_min": "45",
                                                                         "dedup": ""}})
    assert s == 200 and v["settings"]["defaults"] == {"arbiter": False, "limit_wait_max_min": 45}
    assert {o["key"]: o["effective"] for o in v["options"]}["arbiter"] is False
    # 기본 실행 설정 카드를 저장해도 고급 설정은 남는다
    s, v = api(server, "/api/settings", method="POST", body={"defaults": {"max_review": "4"}})
    assert v["settings"]["defaults"] == {"arbiter": False, "limit_wait_max_min": 45, "max_review": 4}
    s, v = api(server, "/api/settings", method="POST", body={"options": {"arbiter": ""}})
    assert "arbiter" not in v["settings"]["defaults"]
    assert api(server, "/api/settings", method="POST", body={"options": {"limit_wait_max_min": "0"}})[0] == 400
    assert api(server, "/api/settings", method="POST", body={"options": {"rm -rf": "1"}})[0] == 400


def test_new_run_passes_advanced_options(tmp_path: Path, monkeypatch):
    seen = {}
    monkeypatch.setattr(Dashboard, "_spawn", lambda self, kind, wd, argv: seen.update(argv=argv) or {"id": "j"})
    Dashboard().start_run({"task": "t", "project": str(tmp_path / "p"), "mock": True,
                           "options": {"arbiter": "false", "dedup": "", "limit_wait_max_min": "30"}})
    argv = seen["argv"]
    assert "--set" in argv and "arbiter=false" in argv and "limit_wait_max_min=30" in argv
    assert not any(a.startswith("dedup=") for a in argv)


# ====================================================================== 28.6 Claude 사용률
STREAM = "\n".join([
    json.dumps({"type": "system", "subtype": "init"}),
    json.dumps({"type": "rate_limit_event", "rate_limit_info": {
        "status": "allowed", "resetsAt": 100, "rateLimitType": "five_hour",
        "unifiedWindows": {"five_hour": {"utilization": 0.07, "resetsAt": 100}, "seven_day": {"utilization": 0.5, "resetsAt": 200}}}}),
    json.dumps({"type": "result", "result": "안녕", "is_error": False, "session_id": "s1"}),
])


def test_parse_stream_and_limits():
    data, info = parse_stream(STREAM)
    assert data["result"] == "안녕" and data["session_id"] == "s1"
    lim = claude_rate_limits(info)
    assert lim["five_hour"] == {"used_percent": 7.0, "resets_at": 100} and lim["seven_day"]["used_percent"] == 50.0
    single, none = parse_stream(json.dumps({"type": "result", "result": "x"}))     # 예전 json 출력
    assert single["result"] == "x" and none is None
    assert parse_stream("not json") == (None, None) and claude_rate_limits(None) is None


def test_claude_limits_saved_and_in_usage(server, isolated_duet_home):
    save_claude_limits({"five_hour": {"used_percent": 12.0, "resets_at": 1}})
    assert load_claude_limits()["limits"]["five_hour"]["used_percent"] == 12.0
    s, u = api(server, "/api/usage")
    assert s == 200 and u["claude_limits"]["limits"]["five_hour"]["used_percent"] == 12.0


def test_limit_wait_uses_claude_reset():
    now = 1000.0
    usage = {"rate_limits": {"status": "rejected", "resets_at": now + 300, "five_hour": {"used_percent": 100, "resets_at": now + 300}}}
    assert limits.reset_from_usage(usage, now) == now + 300
    assert limits.reset_from_usage({"rate_limits": {"seven_day": {"used_percent": 100, "resets_at": now + 50}}}, now) == now + 50


def test_default_claude_args_stream():
    assert load_config(None, global_defaults={}).claude.base_args == ["-p", "--output-format", "stream-json", "--verbose"]


# ====================================================================== 새 실행 창의 워크플로 순서도
def test_workflow_api_has_step_effort_for_diagram(tmp_path: Path):
    from duet.workflow import describe, load_workflow
    cfg = Config()
    wf = describe(load_workflow("existing", None, cfg))
    roles = {r["name"]: r for r in wf["roles"]}
    assert roles["scout"]["effort"] == "low" and roles["scout"]["step_effort"] is None   # None: 설정을 따름
    assert [s["kind"] for s in wf["steps"]] == ["explore", "debate", "build"]
    d = Dashboard()._defaults(None)
    assert d["codex"]["effort_base"] == "medium" and d["codex"]["step_effort"]["review"] == "high"
    assert d["codex"]["effort"] == ""          # 화면의 강도 칸은 비워 둔다(단계별 설정을 지우지 않게)


def test_localhost_redirects_to_cookie_host(server):
    """쿠키는 127.0.0.1 에 있으니, 쿠키 없는 localhost 접속은 같은 서버의 127.0.0.1 로 보낸다."""
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    conn.request("GET", "/#/bench", headers={"Host": f"localhost:{server.port}"})
    r = conn.getresponse()
    assert r.status == 302 and r.getheader("Location") == f"http://127.0.0.1:{server.port}/#/bench"
    conn.close()
    assert req(server, "/", headers={"Host": f"127.0.0.1:{server.port}"})[0] == 403      # 127.0.0.1 은 그대로 안내



# ====================================================================== 디자인 v2: 글꼴·로고
def test_bundled_font_served_with_cache(server):
    s, h, raw = req(server, "/static/fonts/PretendardVariable.woff2")
    assert s == 200 and h["Content-Type"] == "font/woff2" and raw[:4] == b"wOF2"
    assert "max-age" in h["Cache-Control"]
    assert req(server, "/static/fonts/../app.js")[0] == 404          # 정해진 파일만


def test_user_logo_served_only_when_present(server, isolated_duet_home):
    assert req(server, "/logos/claude.svg")[0] == 404
    assert api(server, "/api/server")[1]["logos"] == {"claude": False, "codex": False}
    d = isolated_duet_home / "logos"
    d.mkdir()
    (d / "claude.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    (d / "evil.svg").write_text("<svg/>", encoding="utf-8")
    s, h, raw = req(server, "/logos/claude.svg")
    assert s == 200 and h["Content-Type"] == "image/svg+xml" and raw.startswith(b"<svg")
    assert "sandbox" in h["Content-Security-Policy"] and "script" not in h["Content-Security-Policy"]
    assert req(server, "/logos/evil.svg")[0] == 404                  # 정해진 이름만
    assert api(server, "/api/server")[1]["logos"] == {"claude": True, "codex": False}
    (d / "codex.svg").write_bytes(b"<svg>" + b" " * 400_000 + b"</svg>")
    assert req(server, "/logos/codex.svg")[0] == 404                  # 너무 큰 파일은 무시


def test_settings_api_has_builtin_default_and_model_notes(server):
    """고급 설정은 '기본값으로' 되돌릴 내장 기본값을, 모델 목록은 이름·한 줄 설명을 준다."""
    s, data = api(server, "/api/settings")
    assert s == 200
    opts = {o["key"]: o for o in data["options"]}
    assert all("default" in o and "effective" in o for o in opts.values())
    from duet.config import Config
    assert opts["timeout_sec"]["default"] == Config().timeout_sec
    claude = {m["id"]: m for m in data["suggestions"]["claude"]["models"]}
    assert claude["sonnet"]["label"] == "Sonnet" and claude["sonnet"]["note"]
