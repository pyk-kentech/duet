"""M25: 분업 측정 준비 (DESIGN.md 31장). 실제 claude/codex 는 부르지 않는다(mock)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from duet.bench import (
    FIXED_DESIGN_HEADING, RESULTS_JSON, SUMMARY_MD, BenchError, codex_limit_equiv, grade, load_suite,
    prepare_workdir, run_bench, summarize, week_delta, week_marks,
)
from duet.cli import main
from duet.workspace import Workspace, check_workdir
from tests.test_bench import PYTEST, REFS, make_suite

LARGE = ["issuetrack", "stock-warehouses"]


# ====================================================================== 31.1 large 묶음
def test_large_suite_shape():
    tasks = {t.name: t for t in load_suite("large")}
    assert set(tasks) == set(LARGE)
    assert tasks["issuetrack"].kind == "new" and tasks["stock-warehouses"].kind == "existing"
    assert all(t.fixed_design is not None and t.hidden_tests and t.timeout_sec for t in tasks.values())


@pytest.mark.parametrize("name", LARGE)
def test_large_hidden_tests_pass_on_reference(name, tmp_path: Path):
    task = next(t for t in load_suite("large") if t.name == name)
    wd = tmp_path / "wd"
    prepare_workdir(task, wd)
    shutil.copytree(REFS / name, wd, dirs_exist_ok=True)
    g = grade(task, wd, tmp_path / "eval", pytest_cmd=PYTEST)
    assert g["all_passed"] and g["uncollected"] == 0, g["output_tail"]
    assert g["total"] == task.hidden_tests >= 60                 # 적어 둔 수와 실제 수가 같다


def test_large_start_scores(tmp_path: Path):
    """빈 구현·시작 코드는 import 실패한 파일의 테스트까지 실패로 센다 (부풀지 않게)."""
    tasks = {t.name: t for t in load_suite("large")}
    empty = tmp_path / "empty"
    prepare_workdir(tasks["issuetrack"], empty)
    g = grade(tasks["issuetrack"], empty, tmp_path / "e1", pytest_cmd=PYTEST)
    assert g["passed"] == 0 and g["total"] == tasks["issuetrack"].hidden_tests and g["uncollected"] > 100

    wd = tmp_path / "wd"
    t = tasks["stock-warehouses"]
    prepare_workdir(t, wd)
    assert Workspace(wd).has_commits()
    g = grade(t, wd, tmp_path / "e2", pytest_cmd=PYTEST)
    legacy = (t.path / "hidden" / "test_legacy.py").read_text(encoding="utf-8")
    assert g["passed"] >= legacy.count("def test_") and g["total"] == t.hidden_tests and not g["all_passed"]
    r = subprocess.run([*PYTEST, "-q", "-p", "no:cacheprovider"], cwd=wd, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout                            # 시작 코드 자체 테스트는 통과


def test_grade_counts_uncollected(tmp_path: Path):
    suite = tmp_path / "s" / "t"
    (suite / "hidden").mkdir(parents=True)
    (suite / "bench.toml").write_text('name = "t"\nkind = "new"\nhidden_tests = 3\n', encoding="utf-8")
    (suite / "task.md").write_text("x", encoding="utf-8")
    (suite / "hidden" / "test_a.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (suite / "hidden" / "test_b.py").write_text("import not_here_mod\n\ndef test_1():\n    pass\n\ndef test_2():\n    pass\n",
                                                encoding="utf-8")
    [task] = load_suite(str(tmp_path / "s"))
    wd = tmp_path / "wd"
    wd.mkdir()
    g = grade(task, wd, tmp_path / "e", pytest_cmd=PYTEST)
    assert (g["passed"], g["total"], g["uncollected"], g["all_passed"]) == (1, 3, 2, False)


# ====================================================================== 31.2 고정 설계
def test_prepare_fixed_design_new_and_existing(tmp_path: Path):
    tasks = {t.name: t for t in load_suite("large")}
    new = tmp_path / "new"
    prepare_workdir(tasks["issuetrack"], new, fixed_design=True)
    assert (new / "DESIGN.md").read_text(encoding="utf-8").strip() == \
        tasks["issuetrack"].fixed_design.read_text(encoding="utf-8").strip()

    ex = tmp_path / "ex"
    t = tasks["stock-warehouses"]
    prepare_workdir(t, ex, fixed_design=True)
    text = (ex / "DESIGN.md").read_text(encoding="utf-8")
    original = (t.path / "setup" / "DESIGN.md").read_text(encoding="utf-8").strip()
    assert text.startswith(original) and FIXED_DESIGN_HEADING in text and "합계 불변식" in text
    assert Workspace(ex).dirty_files() == ["DESIGN.md"]
    check_workdir(ex, allow=("DESIGN.md",))                       # --skip-design 이 허용하는 변경


def test_prepare_fixed_design_requires_file(tmp_path: Path):
    suite = make_suite(tmp_path)
    task = next(t for t in load_suite(str(suite)) if t.name == "hello")
    with pytest.raises(BenchError, match="고정 설계"):
        prepare_workdir(task, tmp_path / "wd", fixed_design=True)
    with pytest.raises(BenchError, match="고정 설계"):
        run_bench(suite=str(suite), out_root=tmp_path / "out", mock=True, fixed_design=True, printer=lambda s: None)


def _with_designs(tmp_path: Path) -> Path:
    suite = make_suite(tmp_path)
    for name in ("hello", "old"):
        (suite / name / "design.md").write_text(f"# {name} 고정 설계\n- main.py 하나\n", encoding="utf-8")
    return suite


def test_run_bench_fixed_design_mock_classic_and_extended(tmp_path: Path):
    suite = _with_designs(tmp_path)
    rd = run_bench(suite=str(suite), workflows=["classic", "extended"], task_names=["hello"], out_root=tmp_path / "out",
                   mock=True, fixed_design=True, printer=lambda s: None, pytest_cmd=PYTEST)
    data = json.loads((rd / RESULTS_JSON).read_text(encoding="utf-8"))
    assert data["meta"]["fixed_design"] is True
    rows = {r["workflow"]: r for r in data["rows"]}
    for r in rows.values():
        # 채점됨 (mock 작업자의 결과물·승인 여부는 OS 마다 다를 수 있다)
        assert r["status"] in ("approved", "unapproved") and r["hidden"]["total"] == 2
        steps = [c["step"] for c in json.loads((Path(r["run_dir"]) / "run.json").read_text(encoding="utf-8"))["calls"]]
        assert "propose" not in steps and "synthesize" not in steps        # 설계 토론을 건너뜀
        assert "max_input" in r and "codex_equiv" in r and "week_pct" in r
    assert rows["classic"]["team"] is None
    team = rows["extended"]["team"]
    assert team and team["packages"] >= 1 and team["parts_done"] >= 1 and "reverted" in team
    summary = (rd / SUMMARY_MD).read_text(encoding="utf-8")
    assert "고정 설계" in summary and "## 분업" in summary and "Codex 한도 환산" in summary


def test_cli_fixed_design_flag(tmp_path: Path):
    suite = _with_designs(tmp_path)
    assert main(["bench", "run", "--suite", str(suite), "--task", "old", "--fixed-design", "--mock",
                 "--out", str(tmp_path / "out")]) == 0
    [rd] = list((tmp_path / "out").iterdir())
    wd = Path(json.loads((rd / RESULTS_JSON).read_text(encoding="utf-8"))["rows"][0]["workdir"])
    assert "old 고정 설계" in (wd / "DESIGN.md").read_text(encoding="utf-8")


# ====================================================================== 31.3 결과 열
def _call(agent, inp=0, cached=0, out=0, rl=None):
    return SimpleNamespace(agent=agent, usage={"input_tokens": inp, "cached_input_tokens": cached, "output_tokens": out,
                                               **({"rate_limits": rl} if rl else {})})


def test_codex_limit_equiv():
    assert codex_limit_equiv({"codex": {"input": 100_000, "cached": 80_000, "output": 2_000}}) == 20_000 + 8_000 + 10_000
    assert codex_limit_equiv({}) == 0


def test_week_marks_and_delta():
    st = SimpleNamespace(calls=[
        _call("claude", rl={"five_hour": {"used_percent": 5.0}, "seven_day": {"used_percent": 30.0}}),
        _call("codex", rl={"primary": {"used_percent": 12.0, "window_minutes": 10080},
                           "secondary": {"used_percent": 40.0, "window_minutes": 300}}),
        _call("codex"),                                                  # 한도 기록 없는 호출은 건너뜀
        _call("claude", rl={"seven_day": {"used_percent": 31.5}}),
        _call("codex", rl={"primary": {"used_percent": 13.0, "window_minutes": 10080}}),
    ])
    marks = week_marks(st)
    assert marks == {"claude": (30.0, 31.5), "codex": (12.0, 13.0)}       # Codex 는 가장 긴 창(7일)
    prev: dict = {}
    assert week_delta(marks, prev) == {"claude": 1.5, "codex": 1.0} and prev == {"claude": 31.5, "codex": 13.0}
    # 다음 실행은 앞 실행의 마지막 값과 비교, 창이 바뀌어 값이 줄면 None
    assert week_delta({"claude": (32.0, 33.0), "codex": (2.0, 3.0)}, prev) == {"claude": 1.5, "codex": None}


def test_summary_new_columns():
    rows = [{"task": "a", "workflow": "classic", "rep": 1, "status": "approved", "approved": True, "rounds": 1,
             "seconds": 60, "calls": 7, "usage": {"codex": {"input": 10, "output": 1}}, "hidden": None,
             "codex_equiv": 12345.0, "max_input": {"claude": 50_000, "codex": 90_000},
             "week_pct": {"claude": 1.5, "codex": None}, "team": None}]
    text = summarize({"meta": {"suite": "large", "tasks": ["a"], "repeat": 1, "fixed_design": True}, "rows": rows})
    assert "12,345" in text and "50,000 / 90,000" in text and "1.5%p / -" in text and ", 고정 설계" in text
    assert "## 분업" not in text
