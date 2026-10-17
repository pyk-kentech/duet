"""관리자 UI HTTP 서버 (표준 라이브러리 http.server).

보안:
- 기본은 127.0.0.1 에만 바인딩. Host 헤더를 검사해 DNS 리바인딩을 막는다.
- 시작할 때마다 새 토큰을 만든다. 페이지는 ?t=<토큰> 이 있어야 열리고,
  API 는 X-Duet-Token 헤더가 맞아야 응답한다. 다른 사이트가 브라우저를 통해
  실행 버튼(= 셸 권한이 있는 에이전트 실행)을 누르는 것을 막는다.
- 정적 파일은 화이트리스트, CSP 로 인라인 스크립트 금지.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from duet import procs
from duet.config import CLAUDE_MODEL_SUGGESTIONS, EFFORT_SUGGESTIONS
from duet.doctor import ACTIONS, PATH_PREFIX, action_shell
from duet import __version__
from duet.remote import Remote, RemoteError, package_digest
from duet.settings import LOCAL_MACHINE, SettingsError, load_settings, save_settings, validate_machine
from duet.ui.dashboard import ApiError, Dashboard, dispatch
from duet.ui.terminal import TermJob
from duet.usage import codex_home

STATIC_FILES = {"app.js": "text/javascript; charset=utf-8", "style.css": "text/css; charset=utf-8"}
MAX_BODY = 1_000_000
TOKEN_PLACEHOLDER = "__DUET_TOKEN__"
COOKIE_PREFIX = "duet_t_"
COOKIE_MAX_AGE = 30 * 24 * 3600
TOKEN_FILE = "ui-token"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class DuetServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr: tuple[str, int], dashboard: Dashboard, token: str):
        super().__init__(addr, Handler)
        self.dashboard = dashboard
        self.token = token
        self.loopback = is_loopback(addr[0])
        self.terms: dict[str, TermJob] = {}
        self._terms_lock = threading.Lock()
        self._remote_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.loaded_hash = package_digest()
        self.started_at = time.time()
        self.restart_fn: Callable[["DuetServer"], None] = exec_restart
        self._digest_cache: tuple[float, str] = (0.0, self.loaded_hash)

    # ================================================================ 서버 자신
    def current_hash(self) -> str:
        at, h = self._digest_cache
        if time.monotonic() - at > 5:
            h = package_digest()
            self._digest_cache = (time.monotonic(), h)
        return h

    def server_info(self) -> dict[str, Any]:
        cur = self.current_hash()
        running = [t.title for t in self.terms.values() if t.running]
        return {"version": __version__, "loaded": self.loaded_hash[:12], "current": cur[:12],
                "stale": bool(cur and self.loaded_hash and cur != self.loaded_hash),
                "uptime_sec": int(time.time() - self.started_at), "running_terms": running}

    def restart(self) -> dict[str, Any]:
        running = [t.title for t in self.terms.values() if t.running]
        if running:
            raise ApiError(409, f"진행 중인 터미널 작업이 있어 다시 시작할 수 없습니다: {', '.join(running)}")

        def later() -> None:
            time.sleep(0.4)  # 응답이 브라우저에 도착할 시간
            self.restart_fn(self)

        threading.Thread(target=later, daemon=True).start()
        return {"restarting": True}

    @property
    def port(self) -> int:
        return self.server_address[1]

    def allowed_hosts(self) -> set[str]:
        p = self.port
        return {f"127.0.0.1:{p}", f"localhost:{p}", f"[::1]:{p}"}

    # ================================================================ machines
    def machines(self) -> list[dict[str, Any]]:
        try:
            return list(load_settings().get("machines") or [])
        except SettingsError:
            return []

    def machine(self, mid: str) -> dict[str, Any]:
        for m in self.machines():
            if m["id"] == mid:
                return m
        raise ApiError(404, f"등록되지 않은 머신입니다: {mid}")

    def call(self, machine: str, method: str, args: dict[str, Any]) -> Any:
        if machine == LOCAL_MACHINE:
            return dispatch(self.dashboard, method, args)
        try:
            return Remote(self.machine(machine)).api(method, args)
        except RemoteError as e:
            raise ApiError(e.status, e.message) from e

    def all_projects(self) -> dict[str, Any]:
        local = dispatch(self.dashboard, "projects", {})
        groups = [{"id": LOCAL_MACHINE, "name": "이 머신", "local": True, **local}]
        remotes = self.machines()
        results: dict[str, dict[str, Any]] = {}

        def fetch(m: dict[str, Any]) -> None:
            cached = self._remote_cache.get(m["id"])
            if cached and time.monotonic() - cached[0] < REMOTE_CACHE_SEC:
                results[m["id"]] = cached[1]
                return
            try:
                data = Remote(m).api("projects", {}, timeout=20)
                res = {"projects": data["projects"], "jobs": data["jobs"], "error": None}
            except RemoteError as e:
                res = {"projects": [], "jobs": [], "error": e.message}
            self._remote_cache[m["id"]] = (time.monotonic(), res)
            results[m["id"]] = res

        threads = [threading.Thread(target=fetch, args=(m,), daemon=True) for m in remotes]
        for t in threads:
            t.start()
        for t in threads:
            t.join(25)
        for m in remotes:
            r = results.get(m["id"], {"projects": [], "jobs": [], "error": "응답 없음"})
            groups.append({"id": m["id"], "name": m.get("name") or m["id"], "local": False,
                           "ssh": m["ssh"], "workspace_root": m.get("workspace_root") or "", **r})
        # 예전 화면 호환: 최상위 projects/jobs 는 이 머신 것
        return {"machines": groups, "projects": local["projects"], "jobs": local["jobs"]}

    def probe_machine(self, mid: str) -> dict[str, Any]:
        m = self.machine(mid)
        info = Remote(m).probe()
        if info.get("python") and info["python"] != m.get("python"):
            data = load_settings()
            for x in data["machines"]:
                if x["id"] == mid:
                    x["python"] = info["python"]
            save_settings(data)
        return info

    def deploy_machine(self, mid: str) -> dict[str, Any]:
        m = self.machine(mid)
        if not m.get("python"):
            info = self.probe_machine(mid)
            if not info.get("reachable"):
                raise ApiError(502, info.get("error") or "연결 실패")
            if not info.get("python"):
                raise ApiError(400, "원격에 Python 3.11 이상이 없습니다. 먼저 'uv 설치' → 'Python 3.12 설치'를 하세요.")
            m = self.machine(mid)
        try:
            out = Remote(m).deploy()
        except RemoteError as e:
            raise ApiError(e.status, e.message) from e
        self._remote_cache.pop(mid, None)
        return out

    # ================================================================ settings
    def settings_view(self) -> dict[str, Any]:
        try:
            data = load_settings()
            err = None
        except SettingsError as e:
            data, err = {"workspace_roots": [], "defaults": {}, "machines": []}, str(e)
        from duet.options import schema
        from duet.workflow import list_workflows

        try:
            names = [w["id"] for w in list_workflows(None) if w.get("source") != "error"]
        except Exception:  # noqa: BLE001 - 목록을 못 읽어도 설정 화면은 뜬다
            names = []
        return {"settings": data, "error": err, "suggestions": model_suggestions(),
                "effective": self.dashboard._defaults(None), "options": schema(workflows=names)}

    def save_settings(self, body: dict[str, Any]) -> dict[str, Any]:
        data = load_settings()
        if "workspace_roots" in body:
            data["workspace_roots"] = [str(r).strip() for r in body["workspace_roots"] if str(r).strip()]
        if "defaults" in body:
            # 기본 실행 설정 카드는 자기 칸만 보낸다. 고급 설정(options)에서 저장한 값은 지우지 않는다
            from duet.options import BY_KEY

            kept = {k: v for k, v in (data.get("defaults") or {}).items() if k in BY_KEY}
            data["defaults"] = {**kept, **_clean_defaults(body["defaults"])}
        if "options" in body:
            # 고급 설정 카드 (DESIGN.md 28.4): 빈 값은 '기본값 사용' → 지운다
            from duet.options import BY_KEY, OptionError, parse

            if not isinstance(body["options"], dict):
                raise ApiError(400, "options 는 객체여야 합니다.")
            d = dict(data.get("defaults") or {})
            for k, raw in body["options"].items():
                if k not in BY_KEY:
                    raise ApiError(400, f"알 수 없는 설정입니다: {k}")
                try:
                    v = parse(k, raw)
                except OptionError as e:
                    raise ApiError(400, str(e)) from e
                if v is None:
                    d.pop(k, None)
                else:
                    d[k] = v
            data["defaults"] = d
        try:
            save_settings(data)
        except SettingsError as e:
            raise ApiError(400, str(e)) from e
        return self.settings_view()

    def upsert_machine(self, body: dict[str, Any]) -> dict[str, Any]:
        m = {k: body.get(k) for k in ("id", "name", "ssh", "port", "workspace_root", "python") if body.get(k) not in (None, "")}
        if "port" in m:
            try:
                m["port"] = int(m["port"])
            except (TypeError, ValueError):
                raise ApiError(400, "포트는 숫자여야 합니다.") from None
        try:
            validate_machine(m)
        except SettingsError as e:
            raise ApiError(400, str(e)) from e
        data = load_settings()
        others = [x for x in data["machines"] if x["id"] != m["id"]]
        prev = next((x for x in data["machines"] if x["id"] == m["id"]), {})
        if "python" not in m and prev.get("python") and prev.get("ssh") == m["ssh"]:
            m["python"] = prev["python"]
        data["machines"] = [*others, m]
        try:
            save_settings(data)
        except SettingsError as e:
            raise ApiError(400, str(e)) from e
        self._remote_cache.pop(m["id"], None)
        return self.settings_view()

    def delete_machine(self, mid: str | None) -> dict[str, Any]:
        data = load_settings()
        data["machines"] = [x for x in data["machines"] if x["id"] != mid]
        save_settings(data)
        self._remote_cache.pop(mid or "", None)
        return self.settings_view()

    # ================================================================ setup / terminal jobs
    def actions_view(self) -> dict[str, Any]:
        return {"actions": {a.id: {"title": a.title, "interactive": a.interactive, "note": a.note, "command": a.shell,
                                   "local_command": a.local_command(), "local_available": a.available_locally()}
                            for a in ACTIONS.values()}}

    def start_action(self, machine: str, action_id: Any) -> dict[str, Any]:
        try:
            action = action_shell(str(action_id))
        except KeyError:
            raise ApiError(400, "알 수 없는 동작입니다.") from None
        if machine == LOCAL_MACHINE and not action.available_locally():
            raise ApiError(400, f"'{action.title}' 는 이 OS 에서 지원하지 않습니다. 직접 설치하세요.")
        mode = "pty"
        if machine == LOCAL_MACHINE:
            argv, mode = local_action_argv(action)
        else:
            argv = Remote(self.machine(machine)).term_argv(action.shell)
        with self._terms_lock:
            for t in self.terms.values():
                if t.running and t.machine == machine and t.title == action.title:
                    raise ApiError(409, f"'{action.title}' 가 이미 실행 중입니다.")
            tid = secrets.token_hex(6)
            job = TermJob(id=tid, title=action.title, argv=argv, machine=machine, note=action.note, mode=mode)
            self.terms[tid] = job
        job.start()
        self._remote_cache.pop(machine, None)
        return job.snapshot()

    def _term(self, tid: Any) -> TermJob:
        job = self.terms.get(str(tid))
        if job is None:
            raise ApiError(404, "터미널 작업을 찾을 수 없습니다.")
        return job

    def term(self, tid: Any, offset: int) -> dict[str, Any]:
        return self._term(tid).snapshot(offset)

    def terms_list(self) -> list[dict[str, Any]]:
        out = []
        for t in sorted(self.terms.values(), key=lambda x: x.started_at, reverse=True)[:20]:
            snap = t.snapshot(10**12)
            out.append({k: snap[k] for k in ("id", "title", "machine", "running", "returncode", "started_at")})
        return out

    def term_input(self, tid: Any, text: Any) -> dict[str, Any]:
        if not isinstance(text, str) or len(text) > 4000 or "\x03" in text:
            raise ApiError(400, "입력이 잘못되었습니다.")
        try:
            self._term(tid).write(text)
        except (RuntimeError, OSError) as e:
            raise ApiError(409, str(e)) from e
        return {"ok": True}

    def term_kill(self, tid: Any) -> dict[str, Any]:
        self._term(tid).kill()
        return {"ok": True}

    def url(self) -> str:
        host = self.server_address[0]
        shown = "127.0.0.1" if host in ("", "0.0.0.0", "::") or is_loopback(host) else host
        return f"http://{shown}:{self.port}/?t={self.token}"


class Handler(BaseHTTPRequestHandler):
    server: DuetServer
    protocol_version = "HTTP/1.1"
    server_version = "duet-ui"

    # ---------------------------------------------------------------- plumbing
    def log_message(self, fmt: str, *args: Any) -> None:  # 조용히
        pass

    def _send(self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, data: Any) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _text(self, status: int, text: str) -> None:
        self._send(status, text.encode("utf-8"), "text/plain; charset=utf-8")

    def _host_ok(self) -> bool:
        if not self.server.loopback:
            return True  # 외부 바인딩은 토큰으로만 보호(경고는 시작할 때 출력)
        return self.headers.get("Host", "") in self.server.allowed_hosts()

    def _origin_ok(self) -> bool:
        """Origin 헤더가 있으면 허용 Host 와 같아야 한다 (DESIGN.md 24.2). 없으면(탐색·같은 출처 GET) 통과."""
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        u = urlsplit(origin)
        if u.scheme not in ("http", "https") or not u.netloc:
            return False                  # "null" (sandbox iframe, file://) 등
        allowed = self.server.allowed_hosts() if self.server.loopback else {self.headers.get("Host", "")}
        return u.netloc in allowed

    def _fetch_site_ok(self) -> bool:
        """API 는 같은 출처 요청만 (Sec-Fetch-Site 를 보내는 브라우저). 헤더가 없으면(curl 등) 토큰으로 판단."""
        return self.headers.get("Sec-Fetch-Site", "same-origin") in ("same-origin", "none")

    def _token_ok(self, given: str | None) -> bool:
        return bool(given) and hmac.compare_digest(given.encode(), self.server.token.encode())

    # ---------------------------------------------------------------- verbs
    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        if not self._host_ok():
            self._text(HTTPStatus.FORBIDDEN, "허용되지 않은 Host 입니다.")
            return
        if not self._origin_ok():
            self._text(HTTPStatus.FORBIDDEN, "다른 출처에서 온 요청은 받지 않습니다.")
            return
        url = urlsplit(self.path)
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        path = url.path
        try:
            if method == "GET" and path in ("/", "/index.html"):
                return self._index(query)
            if method == "GET" and path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            if path.startswith("/api/"):
                if not self._fetch_site_ok():
                    return self._json(HTTPStatus.FORBIDDEN, {"error": "다른 사이트에서 온 요청은 받지 않습니다."})
                if not self._token_ok(self.headers.get("X-Duet-Token")):
                    return self._json(HTTPStatus.UNAUTHORIZED,
                                      {"error": "토큰이 맞지 않습니다. 터미널에 출력된 새 주소로 다시 접속하세요."})
                body = self._read_json() if method == "POST" else {}
                return self._json(HTTPStatus.OK, self._api(method, path, query, body))
            self._text(HTTPStatus.NOT_FOUND, "없는 페이지입니다.")
        except ApiError as e:
            self._json(e.status, {"error": e.message})
        except Exception as e:  # noqa: BLE001 - UI 는 죽지 않아야 한다
            print(f"[duet ui] 오류: {type(e).__name__}: {e}", file=sys.stderr)
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"서버 오류: {type(e).__name__}: {e}"})

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ApiError(413, "요청이 너무 큽니다.")
        if length == 0:
            return {}
        # 거절하더라도 본문은 먼저 읽는다. 안 읽고 응답·종료하면 Windows 에서는 연결이 끊긴다(ConnectionAborted)
        raw = self.rfile.read(length)
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            raise ApiError(415, "JSON 요청만 받습니다.")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ApiError(400, "JSON 형식이 잘못되었습니다.") from None
        if not isinstance(data, dict):
            raise ApiError(400, "JSON 객체가 필요합니다.")
        return data

    # ---------------------------------------------------------------- pages
    def _cookie_name(self) -> str:
        return f"{COOKIE_PREFIX}{self.server.port}"   # 같은 PC 의 UI 여러 개가 섞이지 않게 포트별

    def _cookie_token(self) -> str | None:
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie") or "")
        except Exception:  # noqa: BLE001 - 깨진 쿠키는 없는 것으로
            return None
        morsel = jar.get(self._cookie_name())
        return morsel.value if morsel is not None else None

    def _index(self, query: dict[str, str]) -> None:
        """?t= 가 맞으면 쿠키를 심고, 다음부터는 쿠키로 연다 (DESIGN.md 28.1). API 는 쿠키로 열지 않는다."""
        via_query = self._token_ok(query.get("t"))
        if not via_query and not self._token_ok(self._cookie_token()):
            self._send(HTTPStatus.FORBIDDEN, _forbidden_page().encode("utf-8"), "text/html; charset=utf-8")
            return
        extra = None
        if via_query:
            extra = {"Set-Cookie": f"{self._cookie_name()}={self.server.token}; HttpOnly; SameSite=Strict; "
                                   f"Path=/; Max-Age={COOKIE_MAX_AGE}"}
        html = _static_text("index.html").replace(TOKEN_PLACEHOLDER, self.server.token)
        self._send(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8", extra)

    def _static(self, name: str) -> None:
        ctype = STATIC_FILES.get(name)
        if ctype is None:
            self._text(HTTPStatus.NOT_FOUND, "없는 파일입니다.")
            return
        self._send(HTTPStatus.OK, _static_text(name).encode("utf-8"), ctype)

    # ---------------------------------------------------------------- api
    # HTTP 경로 → 대시보드 메서드. 쿼리/본문의 machine 이 원격이면 SSH 로 그 머신의 duet _api 를 부른다.
    ROUTES: dict[tuple[str, str], str] = {
        ("POST", "/api/projects"): "add_project",
        ("DELETE", "/api/projects"): "remove_project",
        ("GET", "/api/runs"): "runs",
        ("GET", "/api/run"): "run",
        ("GET", "/api/entry"): "entry",
        ("GET", "/api/console"): "console",
        ("GET", "/api/design"): "design",
        ("GET", "/api/commits"): "commits",
        ("GET", "/api/diff"): "diff",
        ("GET", "/api/jobs"): "jobs",
        ("POST", "/api/actions/run"): "start_run",
        ("POST", "/api/actions/resume"): "resume",
        ("POST", "/api/actions/stop"): "stop",
        ("GET", "/api/usage"): "usage",
        ("GET", "/api/activity"): "activity",
        ("GET", "/api/doctor"): "doctor",
        ("GET", "/api/defaults"): "defaults",
        ("GET", "/api/workflows"): "workflows",
        ("POST", "/api/projects/prune"): "prune_projects",
        ("GET", "/api/bench"): "bench_list",
        ("GET", "/api/bench/result"): "bench_result",
    }

    def _api(self, method: str, path: str, q: dict[str, str], body: dict[str, Any]) -> Any:
        srv = self.server
        args = {**q, **body}
        machine = str(args.pop("machine", "") or LOCAL_MACHINE)
        special = {
            ("GET", "/api/projects"): lambda: srv.all_projects(),
            ("GET", "/api/server"): lambda: srv.server_info(),
            ("POST", "/api/server/restart"): lambda: srv.restart(),
            ("GET", "/api/settings"): lambda: srv.settings_view(),
            ("POST", "/api/settings"): lambda: srv.save_settings(body),
            ("POST", "/api/machines"): lambda: srv.upsert_machine(body),
            ("DELETE", "/api/machines"): lambda: srv.delete_machine(q.get("id")),
            ("POST", "/api/machines/probe"): lambda: srv.probe_machine(machine),
            ("POST", "/api/machines/deploy"): lambda: srv.deploy_machine(machine),
            ("GET", "/api/setup/actions"): lambda: srv.actions_view(),
            ("POST", "/api/setup/action"): lambda: srv.start_action(machine, body.get("action")),
            ("GET", "/api/term"): lambda: srv.term(q.get("id"), _int(q.get("offset"))),
            ("GET", "/api/terms"): lambda: {"terms": srv.terms_list()},
            ("POST", "/api/term/input"): lambda: srv.term_input(body.get("id"), body.get("text")),
            ("POST", "/api/term/kill"): lambda: srv.term_kill(body.get("id")),
        }
        handler = special.get((method, path))
        if handler is not None:
            return handler()
        name = self.ROUTES.get((method, path))
        if name is None:
            raise ApiError(404, "없는 API 입니다.")
        return srv.call(machine, name, args)


REMOTE_CACHE_SEC = 8.0


def local_action_argv(action) -> tuple[list[str], str]:
    """이 머신에서 동작을 돌리는 argv 와 터미널 방식 (DESIGN.md 27.5)."""
    if procs.IS_WINDOWS:
        argv = procs.powershell_argv(action.local_command())
        if action.interactive_here:
            return [*argv[:-2], "-NoExit", *argv[-2:]], "console"
        return argv, "pipe"
    return ["sh", "-c", PATH_PREFIX + action.shell], "pty"


def model_suggestions() -> dict[str, Any]:
    """모델 선택 상자에 보여줄 후보. Codex 는 ~/.codex/models_cache.json 에서 읽는다."""
    codex: list[dict[str, Any]] = []
    try:
        cache = json.loads((codex_home() / "models_cache.json").read_text(encoding="utf-8"))
        for m in cache.get("models", []):
            if isinstance(m, dict) and m.get("slug") and m.get("visibility") == "list":
                codex.append({"id": m["slug"], "label": m.get("display_name") or m["slug"],
                              "efforts": [e.get("effort") for e in m.get("supported_reasoning_levels") or [] if isinstance(e, dict)],
                              "default_effort": m.get("default_reasoning_level")})
    except (OSError, ValueError, AttributeError):
        pass
    return {
        "claude": {"models": [{"id": x, "label": x} for x in CLAUDE_MODEL_SUGGESTIONS],
                   "efforts": EFFORT_SUGGESTIONS["claude"]},
        "codex": {"models": codex, "efforts": EFFORT_SUGGESTIONS["codex"]},
    }


def _clean_defaults(d: Any) -> dict[str, Any]:
    if not isinstance(d, dict):
        raise ApiError(400, "defaults 는 객체여야 합니다.")
    out: dict[str, Any] = {}
    for k in ("implementer", "reviewer", "synth"):
        if d.get(k):
            out[k] = str(d[k])
    if str(d.get("test_command") or "").strip():
        out["test_command"] = str(d["test_command"]).strip()
    if d.get("block_severity"):
        out["block_severity"] = str(d["block_severity"])
    if isinstance(d.get("require_tests_pass"), bool):
        out["require_tests_pass"] = d["require_tests_pass"]
    if d.get("review_diff") in ("incremental", "full"):
        out["review_diff"] = d["review_diff"]
    if isinstance(d.get("repro_tests"), bool):
        out["repro_tests"] = d["repro_tests"]
    for k in ("debate_rounds", "max_review", "timeout_sec", "stall_rounds"):
        if d.get(k) not in (None, ""):
            try:
                out[k] = int(d[k])
            except (TypeError, ValueError):
                raise ApiError(400, f"{k} 는 숫자여야 합니다.") from None
    for agent in ("claude", "codex"):
        sub = d.get(agent) or {}
        if isinstance(sub, dict):
            clean = {k: str(sub[k]).strip() for k in ("model", "effort") if str(sub.get(k) or "").strip()}
            if clean:
                out[agent] = clean
    return out


def _int(v: str | None) -> int:
    try:
        return int(v or 0)
    except ValueError:
        return 0


def _static_text(name: str) -> str:
    return resources.files("duet.ui").joinpath("static", name).read_text(encoding="utf-8")


def _forbidden_page() -> str:
    return ("<!doctype html><meta charset='utf-8'><title>duet</title>"
            "<link rel='stylesheet' href='/static/style.css'>"
            "<body><main class='main'>"
            "<h1>접속 주소가 맞지 않습니다</h1>"
            "<p><code>duet ui</code> 를 실행한 터미널에 출력된 주소(<code>?t=</code> 포함)로 접속하세요. "
            "서버를 다시 시작하면 주소가 바뀝니다.</p></main></body>")


def make_server(host: str = "127.0.0.1", port: int = 8787, *, dashboard: Dashboard | None = None,
                token: str | None = None, port_tries: int = 20) -> DuetServer:
    dashboard = dashboard or Dashboard()
    token = token or secrets.token_urlsafe(24)
    last_err: OSError | None = None
    for i in range(max(1, port_tries)):
        try:
            return DuetServer((host, port + i if port else 0), dashboard, token)
        except OSError as e:  # 포트 사용 중
            last_err = e
            if not port:
                break
    raise OSError(f"포트를 열 수 없습니다 ({host}:{port}~): {last_err}")


RESTART_TOKEN_ENV = "DUET_UI_TOKEN"
RESTART_PORT_ENV = "DUET_UI_EXACT_PORT"


def exec_restart(server: "DuetServer") -> None:
    """같은 포트·토큰으로 자기 자신을 다시 실행한다(바뀐 duet 코드를 읽도록). 실행 중인 duet run 은 별도 프로세스라 영향 없음."""
    host, port = server.server_address[0], server.port
    env = dict(os.environ)
    env[RESTART_TOKEN_ENV] = server.token
    env[RESTART_PORT_ENV] = "1"
    argv = [sys.executable, "-m", "duet", "ui", "--no-browser", "--host", str(host), "--port", str(port)]
    sys.stdout.flush()
    print("\nUI 를 다시 시작합니다 (같은 주소)...", flush=True)
    if procs.IS_WINDOWS:
        # Windows 의 exec 는 새 프로세스를 띄우고 지금 것을 끝내는 흉내라, 직접 그렇게 한다.
        # 소켓을 먼저 닫지 않는다: 이 함수는 다른 스레드에서 불리는데, 메인 스레드가 기다리던 소켓을 닫으면
        # WinError 10038 로 메인 스레드가 먼저 죽어 새 프로세스를 띄우지 못한다. 새 프로세스는 포트가 풀릴 때까지
        # 다시 시도하고(serve 의 exact 경로), 이 프로세스가 끝나면 소켓은 운영체제가 닫는다.
        subprocess.Popen(argv, env=env)
        os._exit(0)
    server.server_close()
    os.execve(sys.executable, argv, env)


def _print_flush(line: str) -> None:
    # 파이프로 보낼 때(duet ui | tee ...) 접속 주소가 버퍼에 갇히지 않게
    print(line, flush=True)


def saved_token(new: bool = False) -> str:
    """$DUET_HOME/ui-token 의 토큰. 없거나 new 면 새로 만든다 (DESIGN.md 28.1).

    UI 를 다시 켜도 같은 토큰이라 즐겨찾기·쿠키가 계속 맞는다. 파일은 사용자만 읽을 수 있게 둔다.
    """
    from duet.registry import duet_home

    path = duet_home() / TOKEN_FILE
    if not new:
        try:
            tok = path.read_text(encoding="utf-8").strip()
            if len(tok) >= 24:
                return tok
        except OSError:
            pass
    tok = secrets.token_urlsafe(24)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tok + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return tok


def serve(host: str, port: int, *, open_browser: bool = True, extra_projects: list[str] = (),
          printer: Callable[[str], None] = _print_flush, new_token: bool = False) -> None:
    dashboard = Dashboard()
    for p in extra_projects:
        dashboard.registry.add(p)
    # UI 의 '다시 시작'으로 뜬 경우: 같은 토큰·같은 포트 (자식 프로세스에 토큰이 새지 않게 환경에서 뺀다)
    token = os.environ.pop(RESTART_TOKEN_ENV, None) or saved_token(new_token)
    exact = os.environ.pop(RESTART_PORT_ENV, None) == "1"
    server = None
    if exact:
        for _ in range(25):
            try:
                server = make_server(host, port, dashboard=dashboard, token=token, port_tries=1)
                break
            except OSError:
                time.sleep(0.2)
    if server is None:
        server = make_server(host, port, dashboard=dashboard, token=token)
    url = server.url()
    if not server.loopback:
        printer(f"⚠️  {host} 에 바인딩합니다. 같은 네트워크에서 주소와 토큰을 아는 사람은 실행을 시작할 수 있습니다.")
        printer("   가능하면 기본값(127.0.0.1)과 SSH 터널을 쓰세요: ssh -L 8787:127.0.0.1:8787 <서버>")
    printer(f"duet 관리자 UI: {url}")
    printer("종료: Ctrl-C  (UI 를 꺼도 UI 에서 시작한 실행은 계속 돕니다)")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        printer("\nUI 종료")
    finally:
        server.server_close()
