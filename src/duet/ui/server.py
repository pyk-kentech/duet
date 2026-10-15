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
import secrets
import sys
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from duet.ui.dashboard import ApiError, Dashboard

STATIC_FILES = {"app.js": "text/javascript; charset=utf-8", "style.css": "text/css; charset=utf-8"}
MAX_BODY = 1_000_000
TOKEN_PLACEHOLDER = "__DUET_TOKEN__"
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

    @property
    def port(self) -> int:
        return self.server_address[1]

    def allowed_hosts(self) -> set[str]:
        p = self.port
        return {f"127.0.0.1:{p}", f"localhost:{p}", f"[::1]:{p}"}

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
        url = urlsplit(self.path)
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        path = url.path
        try:
            if method == "GET" and path in ("/", "/index.html"):
                return self._index(query)
            if method == "GET" and path.startswith("/static/"):
                return self._static(path[len("/static/"):])
            if path.startswith("/api/"):
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
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            raise ApiError(415, "JSON 요청만 받습니다.")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ApiError(400, "JSON 형식이 잘못되었습니다.") from None
        if not isinstance(data, dict):
            raise ApiError(400, "JSON 객체가 필요합니다.")
        return data

    # ---------------------------------------------------------------- pages
    def _index(self, query: dict[str, str]) -> None:
        if not self._token_ok(query.get("t")):
            self._send(HTTPStatus.FORBIDDEN, _forbidden_page().encode("utf-8"), "text/html; charset=utf-8")
            return
        html = _static_text("index.html").replace(TOKEN_PLACEHOLDER, self.server.token)
        self._send(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8")

    def _static(self, name: str) -> None:
        ctype = STATIC_FILES.get(name)
        if ctype is None:
            self._text(HTTPStatus.NOT_FOUND, "없는 파일입니다.")
            return
        self._send(HTTPStatus.OK, _static_text(name).encode("utf-8"), ctype)

    # ---------------------------------------------------------------- api
    def _api(self, method: str, path: str, q: dict[str, str], body: dict[str, Any]) -> Any:
        d = self.server.dashboard
        routes: dict[tuple[str, str], Callable[[], Any]] = {
            ("GET", "/api/projects"): lambda: {"projects": d.projects(), "jobs": d.jobs_list()},
            ("POST", "/api/projects"): lambda: d.add_project(body.get("path")),
            ("DELETE", "/api/projects"): lambda: d.remove_project(q.get("project")),
            ("GET", "/api/runs"): lambda: d.runs(q.get("project")),
            ("GET", "/api/run"): lambda: d.run(q.get("project"), q.get("run")),
            ("GET", "/api/entry"): lambda: d.entry(q.get("project"), q.get("run"), q.get("file")),
            ("GET", "/api/console"): lambda: d.console(q.get("project"), q.get("run"), _int(q.get("offset"))),
            ("GET", "/api/design"): lambda: d.design(q.get("project"), q.get("run"), q.get("which") or "current"),
            ("GET", "/api/commits"): lambda: d.commits(q.get("project"), q.get("run")),
            ("GET", "/api/diff"): lambda: d.diff(q.get("project"), q.get("run"), q.get("commit") or None),
            ("GET", "/api/jobs"): lambda: {"jobs": d.jobs_list()},
            ("POST", "/api/actions/run"): lambda: d.start_run(body),
            ("POST", "/api/actions/resume"): lambda: d.resume(body),
            ("POST", "/api/actions/stop"): lambda: d.stop(body),
        }
        handler = routes.get((method, path))
        if handler is None:
            raise ApiError(404, "없는 API 입니다.")
        return handler()


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


def _print_flush(line: str) -> None:
    # 파이프로 보낼 때(duet ui | tee ...) 접속 주소가 버퍼에 갇히지 않게
    print(line, flush=True)


def serve(host: str, port: int, *, open_browser: bool = True, extra_projects: list[str] = (),
          printer: Callable[[str], None] = _print_flush) -> None:
    dashboard = Dashboard()
    for p in extra_projects:
        dashboard.registry.add(p)
    server = make_server(host, port, dashboard=dashboard)
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
