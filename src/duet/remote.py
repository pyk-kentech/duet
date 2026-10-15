"""원격 머신(SSH) 지원.

- duet 를 실행 가능한 zip 하나(duet.pyz)로 만들어 원격 ~/.duet/bin/ 에 복사한다(원격엔 Python 3.11+ 만 필요).
- UI 의 원격 조회·동작은 `ssh <머신> <python> ~/.duet/bin/duet.pyz _api <method>` (JSON 은 stdin/stdout).
- SSH 는 키 인증(BatchMode)만 쓴다. ControlMaster 로 연결을 재사용해 폴링을 빠르게 한다.
- 테스트에서는 DUET_SSH 로 가짜 ssh 를 끼운다.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shlex
import zipfile
from pathlib import Path
from typing import Any

import duet
from duet.doctor import PATH_PREFIX
from duet.registry import duet_home
from duet.runner import ExecutableNotFound, ProcessResult, run_process

REMOTE_DIR = "$HOME/.duet/bin"
REMOTE_PYZ = f"{REMOTE_DIR}/duet.pyz"
PYZ_EXTS = {".py", ".md", ".js", ".css", ".html", ".toml"}
FIND_PYTHON = (
    'for p in python3.13 python3.12 python3.11 python3 "$HOME/.local/bin/python3.12"; do '
    'if command -v "$p" >/dev/null 2>&1 && "$p" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; '
    'then command -v "$p"; exit 0; fi; done; '
    'if command -v uv >/dev/null 2>&1; then uv python find ">=3.11" 2>/dev/null && exit 0; fi; exit 3'
)


class RemoteError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status
        self.message = message


# ====================================================================== pyz
_PYZ_CACHE: tuple[bytes, str] | None = None


def _package_files() -> tuple[Path, list[Path]]:
    pkg = Path(duet.__file__).parent
    if not pkg.is_dir():
        raise RemoteError("이 duet 는 zip 에서 실행 중이라 원격 배포 파일을 만들 수 없습니다.", 500)
    files = sorted(f for f in pkg.rglob("*")
                   if f.is_file() and f.suffix in PYZ_EXTS and "__pycache__" not in f.parts)
    return pkg, files


def package_digest() -> str:
    """설치된 duet 코드의 내용 해시. 코드가 바뀌었는지(UI 다시 시작 필요) 판단에도 쓴다."""
    try:
        pkg, files = _package_files()
    except RemoteError:
        return ""
    digest = hashlib.sha256()
    for f in files:
        digest.update(f.relative_to(pkg).as_posix().encode())
        try:
            digest.update(f.read_bytes())
        except OSError:
            pass
    return digest.hexdigest()


def build_pyz() -> tuple[bytes, str]:
    """설치된 duet 패키지로 실행 가능한 zip 을 만든다. (내용, sha256). 내용이 같으면 해시도 같다."""
    global _PYZ_CACHE
    pkg, files = _package_files()
    key = package_digest()
    if _PYZ_CACHE and _PYZ_CACHE[1] == key:
        return _PYZ_CACHE
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        def put(name: str, data: bytes) -> None:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
        put("__main__.py", b"import sys\nfrom duet.cli import main\nsys.exit(main())\n")
        for f in files:
            put("duet/" + f.relative_to(pkg).as_posix(), f.read_bytes())
    data = b"#!/usr/bin/env python3\n" + buf.getvalue()
    _PYZ_CACHE = (data, key)
    return _PYZ_CACHE


# ====================================================================== remote
class Remote:
    def __init__(self, machine: dict[str, Any]):
        self.m = machine
        self.id = machine["id"]
        self.target = machine["ssh"]
        self.port = int(machine.get("port") or 22)

    # ---------------------------------------------------------------- ssh
    @staticmethod
    def ssh_bin() -> str:
        return os.environ.get("DUET_SSH") or "ssh"

    def ssh_argv(self, *, tty: bool = False) -> list[str]:
        ctl = duet_home() / "ssh"
        ctl.mkdir(parents=True, exist_ok=True)
        argv = [self.ssh_bin(), "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                "-o", "ServerAliveInterval=15", "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ControlMaster=auto", "-o", f"ControlPath={ctl}/cm-%C", "-o", "ControlPersist=600",
                "-p", str(self.port)]
        if tty:
            argv.append("-tt")
        return [*argv, "--", self.target]

    def sh(self, script: str, *, stdin: str | None = None, timeout: int = 60) -> ProcessResult:
        try:
            return run_process([*self.ssh_argv(), PATH_PREFIX + script], cwd=Path.home(),
                               timeout_sec=timeout, stdin_text=stdin)
        except ExecutableNotFound as e:
            raise RemoteError("ssh 를 찾을 수 없습니다. OpenSSH 클라이언트를 설치하세요.", 500) from e

    def term_argv(self, shell: str) -> list[str]:
        """터미널 작업(설치·로그인)을 원격에서 돌리는 명령."""
        return [*self.ssh_argv(tty=True), PATH_PREFIX + shell]

    @property
    def python(self) -> str:
        return self.m.get("python") or "python3"

    def _py(self) -> str:
        p = self.python
        return p if p.startswith(("/", "$HOME")) else shlex.quote(p)

    # ---------------------------------------------------------------- probe / deploy
    def probe(self) -> dict[str, Any]:
        # FIND_PYTHON 은 exit 로 끝나므로 서브셸에서 돌린다(뒤의 명령이 이어지게)
        r = self.sh("uname -sm; echo '---'; (" + FIND_PYTHON + "); echo \"---$?\"; "
                    f"cat {REMOTE_PYZ}.sha256 2>/dev/null; echo", timeout=30)
        if r.timed_out:
            return {"reachable": False, "error": "SSH 연결 시간 초과"}
        if r.exit_code == 255 or "---" not in r.stdout:
            msg = (r.stderr.strip().splitlines() or ["SSH 연결 실패"])[-1]
            return {"reachable": False, "error": f"SSH 연결 실패: {msg}",
                    "hint": "키 인증이 필요합니다: ssh-copy-id " + self.target}
        uname, rest = r.stdout.split("---", 1)
        py_part, _, tail = rest.partition("---")
        code_line, _, hash_part = tail.partition("\n")
        python = py_part.strip().splitlines()[-1] if py_part.strip() and code_line.strip() == "0" else ""
        local_hash = build_pyz()[1]
        remote_hash = hash_part.strip()
        return {"reachable": True, "uname": uname.strip(), "python": python,
                "deployed": bool(remote_hash), "up_to_date": remote_hash == local_hash,
                "remote_hash": remote_hash[:12], "local_hash": local_hash[:12]}

    def deploy(self) -> dict[str, Any]:
        data, digest = build_pyz()
        py = self._py()
        script = (
            f'mkdir -p {REMOTE_DIR} && {py} -c "import sys,base64; '
            f"open(sys.argv[1],'wb').write(base64.b64decode(sys.stdin.read()))\" {REMOTE_PYZ}.tmp && "
            f"mv {REMOTE_PYZ}.tmp {REMOTE_PYZ} && printf %s {digest} > {REMOTE_PYZ}.sha256 && "
            f"printf '#!/bin/sh\\nexec %s \"$HOME/.duet/bin/duet.pyz\" \"$@\"\\n' {shlex.quote(self.python)} > {REMOTE_DIR}/duet && "
            f"chmod +x {REMOTE_DIR}/duet && {py} {REMOTE_PYZ} --version"
        )
        r = self.sh(script, stdin=base64.b64encode(data).decode(), timeout=120)
        if not r.ok:
            raise RemoteError(f"배포 실패 (exit {r.exit_code}): {(r.stderr or r.stdout).strip()[-800:]}")
        return {"deployed": True, "version": r.stdout.strip().splitlines()[-1], "hash": digest[:12]}

    # ---------------------------------------------------------------- api
    def api(self, method: str, args: dict[str, Any] | None = None, timeout: int = 60) -> Any:
        r = self.sh(f"{self._py()} {REMOTE_PYZ} _api {shlex.quote(method)}",
                    stdin=json.dumps(args or {}, ensure_ascii=False), timeout=timeout)
        if r.timed_out:
            raise RemoteError(f"{self.id}: 응답 시간 초과", 504)
        if r.exit_code == 255:
            raise RemoteError(f"{self.id}: SSH 연결 실패 — {(r.stderr.strip().splitlines() or [''])[-1]}")
        try:
            out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else None
        except ValueError:
            out = None
        if not isinstance(out, dict):
            hint = "원격에 duet 가 배포되지 않았거나 Python 이 맞지 않습니다. 설정 > 머신에서 '배포'를 누르세요."
            raise RemoteError(f"{self.id}: 잘못된 응답 (exit {r.exit_code}). {hint}\n{(r.stderr or r.stdout).strip()[-400:]}")
        if "error" in out:
            raise RemoteError(out["error"], int(out.get("status") or 500))
        return out.get("ok")
