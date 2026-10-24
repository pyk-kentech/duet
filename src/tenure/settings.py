"""사용자 전역 설정. $TENURE_HOME/settings.json (기본 ~/.tenure/settings.json)

관리자 UI 의 '설정' 화면이 읽고 쓰며, CLI 실행에도 적용된다.

{
  "workspace_roots": ["/home/me/projects"],        # 새 실행 때 고를 상위 폴더 (첫 번째가 기본)
  "defaults": {                                     # tenure.toml 과 같은 형식. 우선순위: CLI > tenure.toml > 여기 > 기본값
    "implementer": "claude", "debate_rounds": 1,
    "claude": {"model": "opus", "effort": "high"},
    "codex": {"model": "gpt-6.1-sol", "effort": "xhigh"}
  },
  "machines": [                                     # 원격 실행용 SSH 머신 (tenure.remote)
    {"id": "lab", "name": "연구실 서버", "ssh": "me@lab", "port": 22, "workspace_root": "~/tenure-projects"}
  ]
}
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from tenure.procs import replace_file
from tenure.registry import tenure_home

SETTINGS_FILENAME = "settings.json"
_lock = threading.Lock()
MACHINE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
SSH_TARGET_RE = re.compile(r"^(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9._:\[\]-]+$")
LOCAL_MACHINE = "local"


class SettingsError(Exception):
    pass


def settings_path(home: Path | None = None) -> Path:
    return (Path(home) if home else tenure_home()) / SETTINGS_FILENAME


def load_settings(home: Path | None = None) -> dict[str, Any]:
    path = settings_path(home)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError) as e:
        raise SettingsError(f"{path} 를 읽을 수 없습니다: {e}") from e
    if not isinstance(data, dict):
        raise SettingsError(f"{path} 형식이 잘못되었습니다.")
    data.setdefault("workspace_roots", [])
    data.setdefault("defaults", {})
    data.setdefault("machines", [])
    return data


def save_settings(data: dict[str, Any], home: Path | None = None) -> None:
    path = settings_path(home)
    validate_settings(data)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        replace_file(tmp, path)


def validate_settings(data: dict[str, Any]) -> None:
    roots = data.get("workspace_roots", [])
    if not isinstance(roots, list) or not all(isinstance(r, str) and r.strip() for r in roots):
        raise SettingsError("workspace_roots 는 경로 문자열 목록이어야 합니다.")
    for r in roots:
        if not (r.startswith("/") or r.startswith("~") or re.match(r"^[A-Za-z]:[\\/]", r) or r.startswith("\\\\")):   # 윈도우 C:\ · UNC
            raise SettingsError(f"작업 폴더 위치는 절대 경로(또는 ~)여야 합니다: {r}")
    if not isinstance(data.get("defaults", {}), dict):
        raise SettingsError("defaults 는 객체여야 합니다.")
    # defaults 는 config 검증으로 확인
    from tenure.config import ConfigError, load_config  # 순환 import 방지

    try:
        load_config(None, None, global_defaults=data.get("defaults") or {})
    except ConfigError as e:
        raise SettingsError(f"기본 설정 오류: {e}") from e
    machines = data.get("machines", [])
    if not isinstance(machines, list):
        raise SettingsError("machines 는 목록이어야 합니다.")
    seen = set()
    for m in machines:
        validate_machine(m)
        if m["id"] in seen:
            raise SettingsError(f"머신 id 가 중복됩니다: {m['id']}")
        seen.add(m["id"])


def validate_machine(m: Any) -> None:
    if not isinstance(m, dict):
        raise SettingsError("머신 정보는 객체여야 합니다.")
    mid = m.get("id")
    if not isinstance(mid, str) or not MACHINE_ID_RE.match(mid) or mid == LOCAL_MACHINE:
        raise SettingsError("머신 id 는 영문 소문자·숫자·-·_ 로 1~32자여야 합니다('local' 제외).")
    ssh = m.get("ssh")
    if not isinstance(ssh, str) or not SSH_TARGET_RE.match(ssh) or ssh.startswith("-"):
        raise SettingsError("SSH 대상은 user@host 또는 host 형식이어야 합니다.")
    port = m.get("port", 22)
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise SettingsError("포트는 1~65535 정수여야 합니다.")
    for key in ("name", "workspace_root", "python"):
        v = m.get(key)
        if v is not None and not isinstance(v, str):
            raise SettingsError(f"{key} 는 문자열이어야 합니다.")
    py = m.get("python")
    if py and not re.match(r"^[\w./~+-]+$", py):
        raise SettingsError("python 경로에 허용되지 않는 문자가 있습니다.")
    root = m.get("workspace_root")
    if root and not re.match(r"^[~/][\w./~+ -]*$", root):
        raise SettingsError("원격 작업 폴더 위치는 / 또는 ~ 로 시작해야 합니다.")


def global_defaults() -> dict[str, Any]:
    """config.load_config 가 쓰는 전역 기본값 층. 설정 파일이 깨졌으면 빈 값."""
    try:
        return load_settings().get("defaults") or {}
    except SettingsError:
        return {}


def expand_root(root: str) -> str:
    return str(Path(root).expanduser())
