"""옛 이름 duet 와의 호환 (DESIGN.md 36.11).

- 환경 변수 DUET_* 는 TENURE_* 가 없을 때 같은 값으로 읽는다(패키지를 불러올 때 한 번 복사).
- 프로젝트 폴더 .duet/ 는 처음 쓸 때 .tenure/ 로 옮긴다(옮길 수 없으면 .duet/ 를 그대로 쓴다).
- 전역 폴더 ~/.duet 는 ~/.tenure 가 없을 때 옮긴다.
- 설정 파일은 tenure.toml 이 없으면 duet.toml 을 읽는다.
"""

from __future__ import annotations

import os
from pathlib import Path

LEGACY_NAME = "duet"
LEGACY_DIR = ".duet"
LEGACY_CONFIG = "duet.toml"
_ENV_OLD, _ENV_NEW = "DUET_", "TENURE_"


def apply_env_aliases(environ: dict | None = None) -> None:
    env = os.environ if environ is None else environ
    for key in [k for k in env if k.startswith(_ENV_OLD)]:
        env.setdefault(_ENV_NEW + key[len(_ENV_OLD):], env[key])


def migrate_dir(new: Path, old: Path) -> Path:
    """new 가 없고 old 가 폴더면 old → new 로 옮긴다. 쓸 경로를 돌려준다(옮기지 못하면 old)."""
    if new.exists() or not old.is_dir():
        return new
    try:
        old.rename(new)
        return new
    except OSError:
        return old


def config_file(workdir: Path, name: str) -> Path:
    """설정 파일 경로: name 이 있으면 그것, 없고 duet.toml 이 있으면 그것, 둘 다 없으면 name."""
    wd = Path(workdir)
    p = wd / name
    if not p.exists() and (wd / LEGACY_CONFIG).is_file():
        return wd / LEGACY_CONFIG
    return p
