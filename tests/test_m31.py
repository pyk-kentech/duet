"""M31: 새 화면(React) 1차 (DESIGN.md 36.7·36.9). 서버가 새 빌드를 / 에서, 옛 화면을 /classic 에서 준다."""

from __future__ import annotations

import re
import threading
import urllib.error
import urllib.request
from importlib import resources

import pytest

from tenure.ui.server import make_server

TOKEN = "t-m31"


@pytest.fixture
def server():
    srv = make_server("127.0.0.1", 0, token=TOKEN)
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def get(srv, path: str, headers: dict | None = None) -> tuple[int, bytes, dict]:
    req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def test_web_build_is_packaged():
    web = resources.files("tenure.ui").joinpath("web")
    assert web.joinpath("index.html").is_file()
    assets = [p.name for p in web.joinpath("assets").iterdir()]
    assert any(n.endswith(".js") for n in assets) and any(n.endswith(".css") for n in assets)


def test_root_serves_new_app_with_token(server):
    s, body, headers = get(server, f"/?t={TOKEN}")
    html = body.decode("utf-8")
    assert s == 200 and f'content="{TOKEN}"' in html and 'name="tenure-token"' in html
    assert "/app/assets/" in html and "__TENURE_TOKEN__" not in html
    assert "Content-Security-Policy" in headers
    js = re.search(r'src="(/app/assets/[^"]+\.js)"', html).group(1)
    s2, body2, h2 = get(server, js)
    assert s2 == 200 and h2["Content-Type"].startswith("text/javascript") and "immutable" in h2["Cache-Control"] and body2


def test_classic_serves_old_ui(server):
    s, body, _ = get(server, f"/classic?t={TOKEN}")
    html = body.decode("utf-8")
    assert s == 200 and "/static/app.js" in html and TOKEN in html


def test_app_assets_are_confined(server):
    assert get(server, "/app/../ui/server.py")[0] == 404
    assert get(server, "/app/assets/..%2F..%2Fserver.py")[0] == 404
    assert get(server, "/app/index.html")[0] == 404          # html 은 / 로만 (토큰을 넣어 준다)
    assert get(server, "/app/assets/nope.js")[0] == 404
    assert get(server, "/app/")[0] == 404


def test_root_without_token_is_forbidden(server):
    assert get(server, "/")[0] == 403


def test_start_run_accepts_auto(tmp_path, monkeypatch):
    import tenure.ui.dashboard as dmod

    seen = {}
    monkeypatch.setattr(dmod, "spawn_detached", lambda argv, *a, **k: (seen.setdefault("argv", argv), type("P", (), {"pid": 1})())[1])
    dmod.Dashboard().start_run({"task": "할일", "project": str(tmp_path / "w"), "workflow": "auto", "mock": True})
    argv = seen["argv"]
    assert argv[argv.index("--workflow") + 1] == "auto"


def test_bench_index_survives_corruption(tmp_path, monkeypatch):
    from tenure import bench

    home = tmp_path / "home"
    monkeypatch.setenv("TENURE_HOME", str(home))
    (home / "bench").mkdir(parents=True)
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        d.mkdir()
        (d / "results.json").write_text('{"meta": {}, "rows": []}', encoding="utf-8")
    (home / "bench" / "index.json").write_text(f'[\n "{a.as_posix()}"\n]]', encoding="utf-8")   # 동시 쓰기로 깨진 모양
    assert a in bench.known_result_dirs()
    bench.remember_result_dir(b)
    import json
    assert json.loads((home / "bench" / "index.json").read_text(encoding="utf-8"))[:2] == [str(b), a.as_posix()]


@pytest.mark.parametrize("root, ok", [(r"C:\work", True), ("D:/proj", True), (r"\\nas\share", True), ("/home/me", True),
                                      ("~/p", True), ("relative", False), ("C:work", False)])
def test_workspace_roots_accept_windows_paths(root, ok):
    from tenure.settings import SettingsError, validate_settings

    if ok:
        validate_settings({"workspace_roots": [root], "defaults": {}, "machines": []})
    else:
        with pytest.raises(SettingsError):
            validate_settings({"workspace_roots": [root], "defaults": {}, "machines": []})
