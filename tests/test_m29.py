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


@pytest.mark.parametrize("name", FRONTIER)
def test_frontier_empty_package_scores_zero(name, tmp_path: Path):
    task = _task(name)
    wd = tmp_path / "wd"
    prepare_workdir(task, wd)
    (wd / name).mkdir()
    (wd / name / "__init__.py").write_text("", encoding="utf-8")
    g = grade(task, wd, tmp_path / "eval", pytest_cmd=PYTEST)
    assert g["passed"] == 0 and g["total"] == task.hidden_tests, g["output_tail"]
