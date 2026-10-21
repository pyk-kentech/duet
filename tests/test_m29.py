"""M29: 어려운 과제 묶음 frontier (DESIGN.md 35장). 실제 claude/codex 는 부르지 않는다."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from duet.bench import grade, load_suite, prepare_workdir

REFS = Path(__file__).parent / "bench_refs"
PYTEST = [sys.executable, "-m", "pytest"]
FRONTIER = ["minire", "minisql", "sheet", "tzrule", "mdlite"]


def _task(name: str):
    return next(t for t in load_suite("frontier") if t.name == name)


def test_frontier_suite_shape():
    tasks = {t.name: t for t in load_suite("frontier")}
    assert set(tasks) == set(FRONTIER)
    for t in tasks.values():
        assert t.kind == "new" and t.max_review == 3 and t.timeout_sec == 3600
        assert t.hidden_tests and t.hidden_tests >= 80, t.name
        assert "최상위" in t.prompt and "테스트도 함께 작성한다" in t.prompt, t.name


@pytest.mark.parametrize("name", FRONTIER)
def test_frontier_reference_passes_all_hidden_tests(name, tmp_path: Path):
    """과제 묶음 자체의 검증: 참조 구현은 숨은 테스트를 모두 통과하고, 수는 bench.toml 의 hidden_tests 와 같다."""
    task = _task(name)
    wd = tmp_path / "wd"
    prepare_workdir(task, wd)
    shutil.copytree(REFS / name, wd, dirs_exist_ok=True)
    g = grade(task, wd, tmp_path / "eval", pytest_cmd=PYTEST)
    assert g["all_passed"] and g["failed"] == 0 and g["errors"] == 0, g["output_tail"]
    assert g["total"] == task.hidden_tests == g["passed"]


BACKLOG = ["shop-backlog", "booking-backlog", "search-backlog"]


def _backlog(name: str):
    return next(t for t in load_suite("backlog") if t.name == name)


def test_backlog_suite_shape():
    tasks = {t.name: t for t in load_suite("backlog")}
    assert set(tasks) == set(BACKLOG)
    for t in tasks.values():
        assert t.kind == "existing" and t.max_review == 3 and t.timeout_sec == 3600 and t.hidden_tests >= 100
        assert "테스트도 함께 작성한다" in t.prompt, t.name
        hidden = list((t.path / "hidden").glob("test_*.py"))
        assert any(p.name.startswith("test_regression") for p in hidden), t.name
        assert sum(1 for p in hidden if p.name.startswith("test_t")) >= 6, t.name


@pytest.mark.parametrize("name", BACKLOG)
def test_backlog_reference_passes_all_hidden_tests(name, tmp_path: Path):
    task = _backlog(name)
    wd = tmp_path / "wd"
    prepare_workdir(task, wd)
    shutil.copytree(REFS / name, wd, dirs_exist_ok=True)
    g = grade(task, wd, tmp_path / "eval", pytest_cmd=PYTEST, timeout_sec=600)
    assert g["all_passed"] and g["total"] == task.hidden_tests == g["passed"], g["output_tail"]


@pytest.mark.parametrize("name", BACKLOG)
def test_backlog_setup_keeps_regressions_and_fails_tickets(name, tmp_path: Path):
    """시작 코드는 기존 동작 회귀 테스트·보이는 테스트는 통과하고, 티켓 테스트는 파일마다 실패가 있어야 한다."""
    import subprocess

    from duet.bench import Task

    task = _backlog(name)
    wd = tmp_path / "wd"
    prepare_workdir(task, wd)
    only_reg = tmp_path / "reg" / "task"
    shutil.copytree(task.path, only_reg)
    for p in (only_reg / "hidden").glob("test_t*.py"):
        p.unlink()
    g = grade(Task("reg", "", "existing", only_reg), wd, tmp_path / "eval-reg", pytest_cmd=PYTEST, timeout_sec=600)
    assert g["all_passed"], g["output_tail"]
    r = subprocess.run([*PYTEST, "-q", "-p", "no:cacheprovider"], cwd=wd, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout[-2000:]
    g2 = grade(task, wd, tmp_path / "eval", pytest_cmd=PYTEST, timeout_sec=600)
    assert not g2["all_passed"] and g2["passed"] < 0.5 * task.hidden_tests


@pytest.mark.parametrize("name", FRONTIER)
def test_frontier_empty_package_scores_zero(name, tmp_path: Path):
    task = _task(name)
    wd = tmp_path / "wd"
    prepare_workdir(task, wd)
    (wd / name).mkdir()
    (wd / name / "__init__.py").write_text("", encoding="utf-8")
    g = grade(task, wd, tmp_path / "eval", pytest_cmd=PYTEST)
    assert g["passed"] == 0 and g["total"] == task.hidden_tests, g["output_tail"]
