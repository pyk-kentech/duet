"""M30: tenure 엔진 기반 (DESIGN.md 36장). 실제 claude/codex 는 부르지 않는다."""

from __future__ import annotations

import json
from pathlib import Path

from tenure import legacy
from tenure.cli import main
from tenure.config import load_config
from tenure.lock import RunLock
from tenure.registry import tenure_home
from tenure.state import LEGACY_DIR, TENURE_DIR, list_run_dirs, project_dir


# ====================================================================== 36.11 옛 이름 duet 호환
def test_env_aliases_copy_old_names_without_overriding():
    env = {"DUET_HOME": "/old", "DUET_MOCK_DELAY": "1", "TENURE_MOCK_DELAY": "2", "OTHER": "x"}
    legacy.apply_env_aliases(env)
    assert env["TENURE_HOME"] == "/old" and env["TENURE_MOCK_DELAY"] == "2" and "TENURE_OTHER" not in env


def test_project_dir_migrates_legacy_folder(tmp_path: Path):
    old = tmp_path / LEGACY_DIR / "runs" / "20261001-000000"
    old.mkdir(parents=True)
    (old / "run.json").write_text("{}", encoding="utf-8")
    assert project_dir(tmp_path) == tmp_path / TENURE_DIR
    assert (tmp_path / TENURE_DIR / "runs" / "20261001-000000" / "run.json").is_file()
    assert not (tmp_path / LEGACY_DIR).exists()
    assert project_dir(tmp_path) == tmp_path / TENURE_DIR          # 두 번째는 그대로


def test_project_dir_keeps_new_folder_when_both_exist(tmp_path: Path):
    (tmp_path / LEGACY_DIR).mkdir()
    (tmp_path / TENURE_DIR).mkdir()
    assert project_dir(tmp_path) == tmp_path / TENURE_DIR and (tmp_path / LEGACY_DIR).is_dir()


def test_home_migrates_legacy_folder(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TENURE_HOME", raising=False)
    monkeypatch.delenv("DUET_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / ".duet").mkdir()
    (tmp_path / ".duet" / "projects.json").write_text("[]", encoding="utf-8")
    assert tenure_home() == tmp_path / ".tenure"
    assert (tmp_path / ".tenure" / "projects.json").is_file() and not (tmp_path / ".duet").exists()


def test_legacy_config_file_is_read(tmp_path: Path):
    (tmp_path / "duet.toml").write_text("max_review = 4\n", encoding="utf-8")
    assert load_config(tmp_path).max_review == 4
    (tmp_path / "tenure.toml").write_text("max_review = 2\n", encoding="utf-8")
    assert load_config(tmp_path).max_review == 2                    # 새 이름이 이긴다


def test_old_runs_and_lock_paths_follow_migration(tmp_path: Path):
    run = tmp_path / LEGACY_DIR / "runs" / "20261001-000000"
    run.mkdir(parents=True)
    (run / "run.json").write_text("{}", encoding="utf-8")
    assert [p.name for p in list_run_dirs(tmp_path)] == ["20261001-000000"]
    with RunLock(tmp_path, command="tenure run"):
        assert (tmp_path / TENURE_DIR / "lock.json").is_file()


def test_mock_run_writes_new_folder_and_cli_name(tmp_path: Path, capsys):
    assert main(["run", "할일 CLI", "--workdir", str(tmp_path), "--mock", "--debate-rounds", "0"]) == 0
    assert (tmp_path / TENURE_DIR / "runs").is_dir() and not (tmp_path / LEGACY_DIR).exists()
    st = json.loads(next((tmp_path / TENURE_DIR / "runs").iterdir()).joinpath("run.json").read_text(encoding="utf-8"))
    assert st["status"].startswith("done")
