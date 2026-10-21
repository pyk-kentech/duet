from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from tenure.config import Config, load_config

FAKE_BIN = Path(__file__).parent / "fake_bin"


@pytest.fixture(autouse=True)
def isolated_tenure_home(tmp_path_factory, monkeypatch) -> Path:
    """테스트가 사용자의 ~/.tenure/projects.json 을 건드리지 않게 한다."""
    home = tmp_path_factory.mktemp("tenure-home")
    monkeypatch.setenv("TENURE_HOME", str(home))
    # 기본 워크플로는 auto(DESIGN.md 36.5)지만, 기존 테스트는 classic 흐름을 가정한다. auto 는 test_m30 이 따로 확인
    import tenure.config as _config
    monkeypatch.setattr(_config, "DEFAULT_WORKFLOW", _config.CLASSIC_WORKFLOW)
    if os.name == "nt":
        monkeypatch.setenv("PYTHONUTF8", "1")      # 테스트가 직접 띄우는 자식 파이썬도 UTF-8 (DESIGN.md 27.7)
    return home


@pytest.fixture(scope="session")
def fake_bin(tmp_path_factory) -> Path:
    """가짜 CLI 폴더. Windows 는 shebang 을 몰라 PATH 로 찾을 수 있게 .cmd 감싸개를 둔 복사본 (DESIGN.md 27.7)."""
    if os.name != "nt":
        return FAKE_BIN
    d = tmp_path_factory.mktemp("fake_bin")
    for f in FAKE_BIN.iterdir():
        if f.is_file():
            shutil.copy2(f, d / f.name)
            if not f.suffix:
                shim = f'@"{sys.executable}" "%~dp0{f.name}" %*\r\n'
                (d / f"{f.name}.cmd").write_bytes(shim.encode("utf-8"))
    return d


@pytest.fixture
def fake_cfg(fake_bin: Path) -> Config:
    """bin 을 가짜 실행 파일로 돌린 Config."""
    return load_config(
        None,
        {
            "claude": {"bin": str(fake_bin / "claude")},
            "codex": {"bin": str(fake_bin / "codex")},
            "timeout_sec": 20,
            # 인자를 그대로 확인하는 시험들은 예전 권한 기준. full·웹·조회는 test_m27 에서 따로 (DESIGN.md 33장)
            "access": "standard", "web_search": "off", "package_lookup": False,
        },
    )


@pytest.fixture
def dump_path(tmp_path: Path) -> Path:
    return tmp_path / "dump.json"


def read_dump(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
