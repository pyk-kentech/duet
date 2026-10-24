"""M14: 벤치마크 (DESIGN.md 20장). 실제 claude/codex 는 부르지 않는다(mock)."""

from __future__ import annotations

import datetime as dt
import json
import shutil
import sys
from pathlib import Path

import pytest

import tenure.orchestrator as orch_mod
from tenure.agents.mock import MockAdapter
from tenure.bench import (
    RESULTS_JSON,
    SUMMARY_MD,
    BenchError,
    grade,
    load_results,
    load_suite,
    parse_pytest_summary,
    pick_tasks,
    prepare_workdir,
    run_bench,
    summarize,
)
from tenure.cli import main
from tenure.workspace import Workspace

REFS = Path(__file__).parent / "bench_refs"
PYTEST = [sys.executable, "-m", "pytest"]


# ====================================================================== 내장 과제 묶음 검증
def test_builtin_suite_shape():
    tasks = {t.name: t for t in load_suite("basic")}
    assert set(tasks) == {"roman", "intervals", "inimini", "textstats", "textstats-maxline"}
    assert tasks["textstats-maxline"].kind == "existing"
    assert all("최상위" in t.prompt or t.kind == "existing" for t in tasks.values())


@pytest.mark.parametrize("name", ["roman", "intervals", "inimini", "textstats", "textstats-maxline"])
def test_hidden_tests_pass_on_reference(name, tmp_path: Path):
    """과제 묶음 자체의 검증: 참조 구현은 숨은 테스트를 모두 통과해야 한다."""
    task = next(t for t in load_suite("basic") if t.name == name)
    wd = tmp_path / "wd"
    prepare_workdir(task, wd)
    shutil.copytree(REFS / name, wd, dirs_exist_ok=True)
    g = grade(task, wd, tmp_path / "eval", pytest_cmd=PYTEST)
    assert g["total"] >= 8 and g["failed"] == 0 and g["errors"] == 0, g["output_tail"]
    assert g["all_passed"]


HARD = ["ledger", "csvq", "ratelimit", "ttlcache", "stock-reservations"]


def test_hard_suite_shape():
    tasks = {t.name: t for t in load_suite("hard")}
    assert set(tasks) == set(HARD)
    assert tasks["stock-reservations"].kind == "existing"
    assert sum(1 for t in tasks.values() if t.kind == "new") == 4


@pytest.mark.parametrize("name", HARD)
def test_hard_hidden_tests_pass_on_reference(name, tmp_path: Path):
    task = next(t for t in load_suite("hard") if t.name == name)
    wd = tmp_path / "wd"
    prepare_workdir(task, wd)
    shutil.copytree(REFS / name, wd, dirs_exist_ok=True)
    g = grade(task, wd, tmp_path / "eval", pytest_cmd=PYTEST)
    assert g["total"] >= 15 and g["failed"] == 0 and g["errors"] == 0, g["output_tail"]
    assert g["all_passed"]


DISPUTE = ["todo", "deepmerge", "duration"]


def test_dispute_suite_shape():
    tasks = {t.name: t for t in load_suite("dispute")}
    assert set(tasks) == set(DISPUTE) and all(t.kind == "new" and t.max_review == 4 for t in tasks.values())


@pytest.mark.parametrize("name", DISPUTE)
def test_dispute_hidden_tests_pass_on_reference(name, tmp_path: Path):
    task = next(t for t in load_suite("dispute") if t.name == name)
    wd = tmp_path / "wd"
    prepare_workdir(task, wd)
    shutil.copytree(REFS / name, wd, dirs_exist_ok=True)
    g = grade(task, wd, tmp_path / "eval", pytest_cmd=PYTEST)
    assert g["total"] >= 12 and g["failed"] == 0 and g["errors"] == 0, g["output_tail"]
    assert g["all_passed"]


def test_hard_existing_setup_fails_only_new_tests(tmp_path: Path):
    import subprocess

    task = next(t for t in load_suite("hard") if t.name == "stock-reservations")
    wd = tmp_path / "wd"
    prepare_workdir(task, wd)
    assert Workspace(wd).has_commits() and len(list((wd / "stock").glob("*.py"))) >= 6
    g = grade(task, wd, tmp_path / "eval", pytest_cmd=PYTEST)
    assert g["failed"] + g["errors"] >= 15 and not g["all_passed"]
    # 기존 동작 테스트는 시작 코드에서 모두 통과
    legacy_only = tmp_path / "legacy"
    shutil.copytree(task.path, legacy_only / "task")
    (legacy_only / "task" / "hidden" / "test_reservations.py").unlink()
    from tenure.bench import Task

    g2 = grade(Task("legacy", "", "existing", legacy_only / "task"), wd, tmp_path / "eval2", pytest_cmd=PYTEST)
    assert g2["all_passed"], g2["output_tail"]
    r = subprocess.run([*PYTEST, "-q", "-p", "no:cacheprovider"], cwd=wd, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_existing_setup_fails_only_new_tests(tmp_path: Path):
    task = next(t for t in load_suite("basic") if t.name == "textstats-maxline")
    wd = tmp_path / "wd"
    prepare_workdir(task, wd)
    ws = Workspace(wd)
    assert ws.has_commits() and not ws.dirty() and (wd / "textstats" / "cli.py").is_file()
    g = grade(task, wd, tmp_path / "eval", pytest_cmd=PYTEST)
    assert g["failed"] >= 10 and not g["all_passed"]          # -L 관련만 실패
    legacy = (task.path / "hidden" / "test_legacy.py").read_text(encoding="utf-8")
    assert g["passed"] >= legacy.count("def test_")
    # setup 자체 테스트는 통과
    import subprocess

    r = subprocess.run([*PYTEST, "-q", "-p", "no:cacheprovider"], cwd=wd, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_grade_ignores_agent_conftest_and_ini(tmp_path: Path):
    task = next(t for t in load_suite("basic") if t.name == "roman")
    wd = tmp_path / "wd"
    shutil.copytree(REFS / "roman", wd)
    (wd / "conftest.py").write_text("import pytest\n@pytest.fixture(autouse=True)\ndef boom():\n    raise RuntimeError\n",
                                    encoding="utf-8")
    (wd / "pytest.ini").write_text("[pytest]\naddopts = --definitely-not-an-option\n", encoding="utf-8")
    g = grade(task, wd, tmp_path / "eval", pytest_cmd=PYTEST)
    assert g["all_passed"], g["output_tail"]


def test_grade_empty_project(tmp_path: Path):
    task = next(t for t in load_suite("basic") if t.name == "intervals")
    wd = tmp_path / "wd"
    wd.mkdir()
    g = grade(task, wd, tmp_path / "eval", pytest_cmd=PYTEST)
    assert not g["all_passed"] and g["passed"] == 0


def test_parse_pytest_summary():
    assert parse_pytest_summary("..F\n3 failed, 27 passed, 1 error in 0.5s") == {"passed": 27, "failed": 3, "errors": 1}
    assert parse_pytest_summary("no tests ran in 0.01s") == {"passed": 0, "failed": 0, "errors": 0}
    assert parse_pytest_summary("x\n2 errors in 0.1s\n") == {"passed": 0, "failed": 0, "errors": 2}


def test_pick_tasks():
    tasks = load_suite("basic")
    assert [t.name for t in pick_tasks(tasks, ["roman"])] == ["roman"]
    with pytest.raises(BenchError, match="없는 과제"):
        pick_tasks(tasks, ["nope"])


# ====================================================================== mock 실행
def make_suite(root: Path) -> Path:
    """mock 에이전트가 만드는 main.py(print('hi'))로 통과하는 작은 과제 묶음."""
    new = root / "suite" / "hello"
    (new / "hidden").mkdir(parents=True)
    (new / "bench.toml").write_text('name = "hello"\ndescription = "d"\nkind = "new"\n', encoding="utf-8")
    (new / "task.md").write_text("main.py 를 만든다", encoding="utf-8")
    (new / "hidden" / "test_hello.py").write_text(
        "import pathlib, subprocess, sys\n"
        "def test_main_exists():\n    assert pathlib.Path('main.py').is_file()\n"
        "def test_prints():\n    r = subprocess.run([sys.executable, 'main.py'], capture_output=True, text=True)\n"
        "    assert r.stdout.strip() == 'hi'\n", encoding="utf-8")
    ex = root / "suite" / "old"
    (ex / "hidden").mkdir(parents=True)
    (ex / "setup").mkdir()
    (ex / "setup" / "README.md").write_text("# old\n", encoding="utf-8")
    (ex / "bench.toml").write_text('name = "old"\nkind = "existing"\nmax_review = 1\n', encoding="utf-8")
    (ex / "task.md").write_text("기능 추가", encoding="utf-8")
    (ex / "hidden" / "test_old.py").write_text(
        "import pathlib\ndef test_readme_kept():\n    assert pathlib.Path('README.md').read_text() == '# old\\n'\n"
        "def test_never():\n    assert False\n", encoding="utf-8")
    return root / "suite"


def test_run_bench_mock(tmp_path: Path):
    suite = make_suite(tmp_path)
    lines: list[str] = []
    rd = run_bench(suite=str(suite), workflows=["classic", "lean"], out_root=tmp_path / "out", mock=True,
                   printer=lines.append, pytest_cmd=PYTEST, now=dt.datetime(2026, 10, 16, 12, 0, 0))
    assert rd == tmp_path / "out" / "20261016-120000"
    data = json.loads((rd / RESULTS_JSON).read_text(encoding="utf-8"))
    rows = {(r["task"], r["workflow"]): r for r in data["rows"]}
    assert len(rows) == 4 and data["meta"]["mock"] is True
    hello = rows[("hello", "classic")]
    assert hello["status"] == "approved" and hello["rounds"] == 2 and hello["hidden"]["all_passed"]
    assert hello["hidden"] == {**hello["hidden"], "passed": 2, "total": 2}
    old = rows[("old", "lean")]
    assert old["status"] == "unapproved" and old["rounds"] == 1            # bench.toml max_review = 1
    assert old["hidden"]["passed"] == 1 and old["hidden"]["failed"] == 1   # README 는 그대로, 일부러 실패 1개
    assert (Path(old["workdir"]) / ".git").is_dir()
    summary = (rd / SUMMARY_MD).read_text(encoding="utf-8")
    assert "| classic | 2 | 1/2 |" in summary and "| lean |" in summary
    assert "승인했는데 실패" in summary
    assert any("[1/4] hello × classic #1: 승인, 2라운드, 숨은 테스트 2/2" in ln for ln in lines)
    assert not (rd / "_grade").exists()


def test_run_bench_stops_on_rate_limit(tmp_path: Path, monkeypatch):
    suite = make_suite(tmp_path)
    monkeypatch.setattr(orch_mod, "make_agents", lambda cfg, *, mock: {
        "claude": MockAdapter(label="claude", rate_limit_on_calls={1}), "codex": MockAdapter(label="codex")})
    lines: list[str] = []
    rd = run_bench(suite=str(suite), out_root=tmp_path / "out", mock=True, printer=lines.append, pytest_cmd=PYTEST)
    rows = load_results(rd)["rows"]
    assert len(rows) == 1 and rows[0]["status"] == "stopped" and rows[0]["hidden"] is None
    assert any("벤치마크를 멈춥니다" in ln for ln in lines)


def test_run_bench_orchestrator_error_row(tmp_path: Path):
    suite = make_suite(tmp_path)
    rd = run_bench(suite=str(suite), workflows=["nope"], task_names=["hello"], out_root=tmp_path / "out",
                   mock=True, printer=lambda s: None, pytest_cmd=PYTEST)
    [row] = load_results(rd)["rows"]
    assert row["status"] == "error" and "찾을 수 없습니다" in row["error"]


def test_summarize_handles_empty():
    assert "실행 0번" in summarize({"meta": {"suite": "x", "tasks": [], "repeat": 1}, "rows": []})


# ====================================================================== CLI
def test_cli_real_run_needs_yes(tmp_path: Path, capsys):
    assert main(["bench", "run", "--task", "roman", "--out", str(tmp_path / "out")]) == 2
    out = capsys.readouterr().out
    assert "--yes" in out and "1번 실행" in out
    assert not (tmp_path / "out").exists()


def test_cli_mock_report_list(tmp_path: Path, capsys):
    suite = make_suite(tmp_path)
    assert main(["bench", "run", "--suite", str(suite), "--task", "hello", "--mock",
                 "--out", str(tmp_path / "out")]) == 0
    [rd] = list((tmp_path / "out").iterdir())
    capsys.readouterr()
    assert main(["bench", "report", str(rd)]) == 0
    assert "## 워크플로별" in capsys.readouterr().out
    assert main(["bench", "report", str(tmp_path)]) == 2
    assert main(["bench", "list"]) == 0
    out = capsys.readouterr().out
    assert "textstats-maxline" in out and "기존 프로젝트" in out
    assert main(["bench", "run", "--suite", str(tmp_path / "none"), "--mock"]) == 2
