from __future__ import annotations

import json
from pathlib import Path

import pytest

from duet.config import Config, load_config

FAKE_BIN = Path(__file__).parent / "fake_bin"


@pytest.fixture(autouse=True)
def isolated_duet_home(tmp_path_factory, monkeypatch) -> Path:
    """테스트가 사용자의 ~/.duet/projects.json 을 건드리지 않게 한다."""
    home = tmp_path_factory.mktemp("duet-home")
    monkeypatch.setenv("DUET_HOME", str(home))
    return home


@pytest.fixture
def fake_bin() -> Path:
    return FAKE_BIN


@pytest.fixture
def fake_cfg(fake_bin: Path) -> Config:
    """bin 을 가짜 실행 파일로 돌린 Config."""
    return load_config(
        None,
        {
            "claude": {"bin": str(fake_bin / "claude")},
            "codex": {"bin": str(fake_bin / "codex")},
            "timeout_sec": 20,
        },
    )


@pytest.fixture
def dump_path(tmp_path: Path) -> Path:
    return tmp_path / "dump.json"


def read_dump(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
