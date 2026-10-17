"""벤치마크: 같은 과제 묶음을 워크플로별로 돌리고 숨은 수용 테스트로 채점한다 (DESIGN.md 20장).

과제 폴더: bench.toml(name, description, kind=new|existing, max_review, timeout_sec), task.md, setup/, hidden/,
design.md(선택: --fixed-design 일 때 모든 워크플로가 쓰는 같은 설계, DESIGN.md 31.2)
결과: <out>/<시각>/results.json (실행별 행) + summary.md (워크플로별 집계)
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import re
import shutil
import sys
import time
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Callable, Sequence

from duet import procs
from duet.config import CLASSIC_WORKFLOW, Config
from duet.runner import augmented_path, env_drops, run_process
from duet.state import (
    DONE_APPROVED,
    DONE_DESIGN,
    DONE_UNAPPROVED,
    FAILED,
    STOPPED_RATE_LIMIT,
    STOPPED_USER,
    RunState,
)
from duet.workspace import Workspace

BUILTIN_SUITE = "basic"
HIDDEN_DIR = "duet_hidden_tests"
GRADE_TIMEOUT_SEC = 300
RESULTS_JSON = "results.json"
SUMMARY_MD = "summary.md"
FIXED_DESIGN = "design.md"
FIXED_DESIGN_HEADING = "## 이번 변경 (벤치마크 고정 설계)"
# Codex 요금표 비율: 미캐시 입력 1, 캐시 입력 0.1, 출력 5 (DESIGN.md 17·21장, 31.3)
CODEX_WEIGHTS = (1.0, 0.1, 5.0)

Printer = Callable[[str], None]

STATUS = {DONE_APPROVED: "approved", DONE_UNAPPROVED: "unapproved", DONE_DESIGN: "design_only",
          STOPPED_RATE_LIMIT: "stopped", STOPPED_USER: "stopped", FAILED: "failed"}
STATUS_KO = {"approved": "승인", "unapproved": "미승인", "design_only": "설계만", "stopped": "중단",
             "failed": "실패", "error": "오류"}


class BenchError(Exception):
    """사용자에게 그대로 보여줄 오류."""


@dataclass
class Task:
    name: str
    description: str
    kind: str            # "new" | "existing"
    path: Path
    max_review: int | None = None
    timeout_sec: int | None = None
    hidden_tests: int | None = None   # 숨은 테스트 수. 모이지 않은 테스트(import 실패)를 실패로 센다 (DESIGN.md 31.1)

    @property
    def prompt(self) -> str:
        return (self.path / "task.md").read_text(encoding="utf-8").strip()

    @property
    def fixed_design(self) -> Path | None:
        p = self.path / FIXED_DESIGN
        return p if p.is_file() else None


# ====================================================================== suites
def suite_path(spec: str) -> Path:
    """'basic' 같은 내장 이름 또는 폴더 경로."""
    if spec and ("/" in spec or "\\" in spec or spec.startswith((".", "~"))):
        p = Path(spec).expanduser()
    else:
        p = Path(str(resources.files("duet").joinpath("bench_suites", spec or BUILTIN_SUITE)))
    if not p.is_dir():
        raise BenchError(f"과제 묶음을 찾을 수 없습니다: {spec} ({p})")
    return p


def builtin_suites() -> list[str]:
    root = Path(str(resources.files("duet").joinpath("bench_suites")))
    return sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []


def load_suite(spec: str = BUILTIN_SUITE) -> list[Task]:
    root = suite_path(spec)
    tasks = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        meta_path = d / "bench.toml"
        if not meta_path.is_file():
            continue
        try:
            meta = tomllib.loads(meta_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise BenchError(f"{meta_path}: {e}") from e
        kind = meta.get("kind", "new")
        if kind not in ("new", "existing"):
            raise BenchError(f"{meta_path}: kind 는 new 또는 existing 이어야 합니다: {kind!r}")
        if not (d / "task.md").is_file() or not (d / "hidden").is_dir():
            raise BenchError(f"{d}: task.md 와 hidden/ 이 있어야 합니다")
        if kind == "existing" and not (d / "setup").is_dir():
            raise BenchError(f"{d}: existing 과제는 setup/ 이 있어야 합니다")
        tasks.append(Task(name=str(meta.get("name") or d.name), description=str(meta.get("description") or ""),
                          kind=kind, path=d, max_review=meta.get("max_review"), timeout_sec=meta.get("timeout_sec"),
                          hidden_tests=meta.get("hidden_tests")))
    if not tasks:
        raise BenchError(f"{root} 에 과제가 없습니다 (bench.toml 이 있는 하위 폴더)")
    return tasks


def pick_tasks(tasks: list[Task], names: Sequence[str] | None) -> list[Task]:
    if not names:
        return tasks
    by = {t.name: t for t in tasks}
    unknown = [n for n in names if n not in by]
    if unknown:
        raise BenchError(f"없는 과제: {', '.join(unknown)} (가능: {', '.join(by)})")
    return [by[n] for n in names]


# ====================================================================== prepare / grade
def prepare_workdir(task: Task, wd: Path, *, fixed_design: bool = False) -> None:
    """작업 폴더를 만든다. existing 과제는 setup/ 을 복사하고 커밋해 '기존 프로젝트'로 만든다.

    fixed_design: 과제의 design.md 를 DESIGN.md 로 둔다(기존 과제는 시작 코드의 DESIGN.md 끝에 붙임, 커밋 안 함).
    """
    wd.mkdir(parents=True, exist_ok=True)
    setup = task.path / "setup"
    if setup.is_dir():
        shutil.copytree(setup, wd, dirs_exist_ok=True)
    if task.kind == "existing":
        ws = Workspace(wd)
        ws.ensure_repo()
        ws.commit_all("bench: setup")
    if fixed_design:
        if task.fixed_design is None:
            raise BenchError(f"{task.name}: 고정 설계({FIXED_DESIGN})가 없습니다")
        text = task.fixed_design.read_text(encoding="utf-8").strip()
        target = wd / "DESIGN.md"
        if task.kind == "existing" and target.is_file():
            text = target.read_text(encoding="utf-8").rstrip() + f"\n\n{FIXED_DESIGN_HEADING}\n\n" + text
        target.write_text(text + "\n", encoding="utf-8")


def default_pytest_cmd() -> list[str]:
    """채점용 pytest. 지금 인터프리터에 pytest 가 있으면 그것, 없으면 uvx, 그것도 없으면 python3 -m pytest."""
    if importlib.util.find_spec("pytest") is not None:
        return [sys.executable, "-m", "pytest"]
    uvx = shutil.which("uvx", path=augmented_path(None))
    if uvx:
        return [uvx, "pytest"]
    return [procs.PYTHON_CMD, "-m", "pytest"]


_SUMMARY_RE = re.compile(r"(\d+) (passed|failed|errors?)\b")


def parse_pytest_summary(output: str) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "errors": 0}
    for line in reversed(output.splitlines()):
        found = _SUMMARY_RE.findall(line)
        if found:
            for n, kind in found:
                counts["errors" if kind.startswith("error") else kind] += int(n)
            break
    return counts


def grade(task: Task, wd: Path, eval_dir: Path, *, pytest_cmd: Sequence[str] | None = None,
          timeout_sec: int = GRADE_TIMEOUT_SEC) -> dict[str, Any]:
    """작업 폴더를 복사해 숨은 테스트를 넣고 돌린다. 에이전트의 pytest 설정·conftest 는 쓰지 않는다."""
    if eval_dir.exists():
        shutil.rmtree(eval_dir)
    shutil.copytree(wd, eval_dir, ignore=shutil.ignore_patterns(".git", ".duet", "__pycache__", ".pytest_cache"))
    hidden = eval_dir / HIDDEN_DIR
    shutil.copytree(task.path / "hidden", hidden)
    ini = hidden / "pytest.ini"
    ini.write_text("[pytest]\n", encoding="utf-8")
    # 한 파일의 import 실패가 다른 파일의 채점까지 막지 않게 (DESIGN.md 20.3)
    cmd = [*(pytest_cmd or default_pytest_cmd()), "-q", "-p", "no:cacheprovider", "--continue-on-collection-errors", "-c", str(ini),
           "--rootdir", str(eval_dir), "--confcutdir", str(hidden), str(hidden)]
    cfg = Config()
    r = run_process(cmd, eval_dir, timeout_sec=timeout_sec,
                    env={"PYTHONPATH": str(eval_dir), "PYTHONDONTWRITEBYTECODE": "1"},
                    drop_env=env_drops(cfg.env_strip, cfg.env_keep))
    out = (r.stdout or "") + ("\n" + r.stderr if r.stderr else "")
    counts = parse_pytest_summary(r.stdout or "")
    total = counts["passed"] + counts["failed"] + counts["errors"]
    # import 실패한 파일은 테스트 수 대신 오류 1개로만 잡힌다 → 알려진 개수로 맞춰 빠진 만큼 실패로 센다
    uncollected = max((task.hidden_tests or 0) - counts["passed"] - counts["failed"], 0) if task.hidden_tests else 0
    if uncollected:
        total = counts["passed"] + counts["failed"] + uncollected
    return {"passed": counts["passed"], "failed": counts["failed"], "errors": counts["errors"], "total": total,
            "uncollected": uncollected,
            "all_passed": total > 0 and counts["passed"] == total and r.exit_code == 0,
            "exit_code": r.exit_code, "timed_out": r.timed_out, "output_tail": out[-3000:]}


# ====================================================================== run
def _usage(st: RunState) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for c in st.calls:
        u = c.usage or {}
        t = out.setdefault(c.agent, {"input": 0, "cached": 0, "output": 0, "calls": 0})
        t["calls"] += 1
        t["input"] += int(u.get("input_tokens") or 0)
        t["cached"] += int(u.get("cached_input_tokens") or 0)
        t["output"] += int(u.get("output_tokens") or 0)
    return out


def _max_input(st: RunState) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in st.calls:
        n = int((c.usage or {}).get("input_tokens") or 0)
        out[c.agent] = max(out.get(c.agent, 0), n)
    return out


def codex_limit_equiv(usage: dict[str, dict[str, int]]) -> float:
    """Codex 한도 환산 = 미캐시 입력 + 0.1×캐시 + 5×출력 (DESIGN.md 31.3)"""
    u = usage.get("codex") or {}
    cached = u.get("cached", 0)
    w_in, w_cache, w_out = CODEX_WEIGHTS
    return round(max(u.get("input", 0) - cached, 0) * w_in + cached * w_cache + u.get("output", 0) * w_out, 1)


def _weekly_percent(rl: Any) -> float | None:
    """호출에 기록된 한도 요약에서 7일 창 사용률. Claude 는 seven_day, Codex 는 가장 긴 창."""
    if not isinstance(rl, dict):
        return None
    w = rl.get("seven_day")
    if not isinstance(w, dict):
        wins = [x for x in (rl.get("primary"), rl.get("secondary")) if isinstance(x, dict)]
        w = max(wins, key=lambda x: x.get("window_minutes") or 0) if wins else None
    v = (w or {}).get("used_percent")
    return float(v) if isinstance(v, (int, float)) else None


def week_marks(st: RunState) -> dict[str, tuple[float, float]]:
    """CLI 별 (첫 호출, 마지막 호출)의 7일 창 사용률."""
    out: dict[str, tuple[float, float]] = {}
    for c in st.calls:
        v = _weekly_percent((c.usage or {}).get("rate_limits"))
        if v is None:
            continue
        first = out[c.agent][0] if c.agent in out else v
        out[c.agent] = (first, v)
    return out


def week_delta(marks: dict[str, tuple[float, float]], prev: dict[str, float]) -> dict[str, float | None]:
    """이번 실행의 사용률 변화. 앞 실행의 마지막 값이 있으면 그것과, 없으면 첫 호출과 비교. 창이 바뀌면 None."""
    out: dict[str, float | None] = {}
    for cli, (first, last) in marks.items():
        base = prev.get(cli, first)
        out[cli] = round(last - base, 1) if last >= base else None
        prev[cli] = last
    return out


def _team(st: RunState) -> dict[str, Any] | None:
    t = st.team or {}
    if not t.get("plan"):
        return None
    parts = t.get("parts") or {}
    return {"packages": len(t["plan"].get("packages") or []), "fallback": t.get("fallback"),
            "parts_done": len(parts), "reverted": sum(len(r.get("reverted") or []) for r in parts.values())}


def _row(task: Task, workflow: str, rep: int, wd: Path, seconds: float, outcome: Any | None,
         error: str | None, hidden: dict[str, Any] | None) -> dict[str, Any]:
    row: dict[str, Any] = {"task": task.name, "kind": task.kind, "workflow": workflow, "rep": rep,
                           "workdir": str(wd), "seconds": round(seconds, 1)}
    if outcome is None:
        row.update(status="error", error=error, approved=False, rounds=0, calls=0, usage={}, hidden=hidden)
        return row
    st: RunState = outcome.state
    last_test = st.tests[max(st.tests, key=int)] if st.tests else None
    cost = sum(float((c.usage or {}).get("cost_usd") or 0) for c in st.calls)
    usage = _usage(st)
    row.update(status=STATUS.get(st.status, st.status), approved=st.status == DONE_APPROVED,
               arbiter=st.stop_reason if (st.stop_reason or "").startswith("arbiter") else None,
               stop_reason=st.stop_reason, rounds=len(st.review_history), calls=len(st.calls),
               usage=usage, cost_usd=round(cost, 4), run_dir=str(outcome.run_dir),
               own_tests=last_test.get("status") if last_test else None, hidden=hidden, error=st.error,
               max_input=_max_input(st), codex_equiv=codex_limit_equiv(usage), team=_team(st))
    if st.limit_waited_sec:
        row["limit_wait_sec"] = round(st.limit_waited_sec, 1)   # 소요 시간에서 뺄 수 있게 (DESIGN.md 25.1)
    return row


def run_bench(*, suite: str = BUILTIN_SUITE, workflows: Sequence[str] = (CLASSIC_WORKFLOW,),
              task_names: Sequence[str] | None = None, repeat: int = 1, max_review: int | None = None,
              out_root: Path, mock: bool = False, printer: Printer = print, verbose: bool = False,
              pytest_cmd: Sequence[str] | None = None, now: dt.datetime | None = None,
              wait_on_limit: bool = False, fixed_design: bool = False) -> Path:
    """벤치마크를 돌리고 결과 폴더를 돌려준다. 한도 도달·사용자 중단이면 거기서 멈춘다."""
    from duet.orchestrator import Orchestrator, OrchestratorError, RunOptions

    tasks = pick_tasks(load_suite(suite), task_names)
    if fixed_design:
        missing = [t.name for t in tasks if t.fixed_design is None]
        if missing:
            raise BenchError(f"고정 설계({FIXED_DESIGN})가 없는 과제: {', '.join(missing)}")
    plan = [(t, w, n) for t in tasks for w in workflows for n in range(1, repeat + 1)]
    result_dir = Path(out_root).expanduser() / (now or dt.datetime.now()).strftime("%Y%m%d-%H%M%S")
    result_dir.mkdir(parents=True, exist_ok=False)
    remember_result_dir(result_dir)
    meta = {"suite": suite, "workflows": list(workflows), "tasks": [t.name for t in tasks], "repeat": repeat,
            "max_review": max_review, "mock": mock, "wait_on_limit": wait_on_limit, "fixed_design": fixed_design,
            "started": dt.datetime.now().isoformat(timespec="seconds")}
    rows: list[dict[str, Any]] = []
    prev_week: dict[str, float] = {}
    printer(f"벤치마크: 과제 {len(tasks)}개 × 워크플로 {len(workflows)}개 × {repeat}회 = {len(plan)}번 실행"
            + (" (mock)" if mock else "") + f" → {result_dir}")
    for i, (task, workflow, rep) in enumerate(plan, 1):
        wd = result_dir / task.name / f"{workflow}-{rep}"
        printer(f"[{i}/{len(plan)}] {task.name} × {workflow} #{rep} 실행 중...")
        prepare_workdir(task, wd, fixed_design=fixed_design)
        orch = Orchestrator(printer=printer if verbose else (lambda line: None))
        overrides: dict[str, Any] = {"workflow": workflow}
        if wait_on_limit:
            overrides["wait_on_limit"] = True
        if max_review or task.max_review:
            overrides["max_review"] = max_review or task.max_review
        if task.timeout_sec:
            overrides["timeout_sec"] = task.timeout_sec
        started = time.monotonic()
        outcome, error = None, None
        try:
            outcome = orch.run(RunOptions(task=task.prompt, workdir=wd, mock=mock, overrides=overrides, register=False,
                                          skip_design=fixed_design))
        except OrchestratorError as e:
            error = str(e)
        seconds = time.monotonic() - started
        hidden = None
        if outcome is not None and outcome.state.status in (DONE_APPROVED, DONE_UNAPPROVED):
            hidden = grade(task, wd, result_dir / "_grade" / task.name / f"{workflow}-{rep}", pytest_cmd=pytest_cmd)
        row = _row(task, workflow, rep, wd, seconds, outcome, error, hidden)
        if outcome is not None:
            row["week_pct"] = week_delta(week_marks(outcome.state), prev_week)
        rows.append(row)
        _save(result_dir, meta, rows)
        printer(f"[{i}/{len(plan)}] {task.name} × {workflow} #{rep}: {describe_row(row)}")
        if row["status"] == "stopped":
            printer("한도 도달 또는 중단으로 벤치마크를 멈춥니다. 남은 실행은 돌리지 않았습니다. "
                    f"지금까지 결과: {result_dir / SUMMARY_MD}")
            break
    shutil.rmtree(result_dir / "_grade", ignore_errors=True)
    printer(f"요약: {result_dir / SUMMARY_MD}")
    return result_dir


def describe_row(row: dict[str, Any]) -> str:
    parts = [STATUS_KO.get(row["status"], row["status"]) + (" (중재)" if row.get("arbiter") == "arbiter" else "")]
    if row.get("rounds"):
        parts.append(f"{row['rounds']}라운드")
    h = row.get("hidden")
    if h:
        parts.append(f"숨은 테스트 {h['passed']}/{h['total']}" + (" (시간 초과)" if h.get("timed_out") else ""))
    parts.append(_fmt_sec(row.get("seconds") or 0))
    tok = sum(u.get("input", 0) for u in (row.get("usage") or {}).values())
    if tok:
        parts.append(f"입력 {tok:,} 토큰")
    if row.get("error") and row["status"] in ("error", "failed"):
        parts.append(str(row["error"])[:120])
    return ", ".join(parts)


def _fmt_sec(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 60}분 {sec % 60}초" if sec >= 60 else f"{sec}초"


def _save(result_dir: Path, meta: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    data = {"meta": meta, "rows": rows}
    tmp = result_dir / (RESULTS_JSON + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(result_dir / RESULTS_JSON)
    (result_dir / SUMMARY_MD).write_text(summarize(data), encoding="utf-8")


# ====================================================================== summary
def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


INDEX_FILE = "index.json"
INDEX_MAX = 200


def remember_result_dir(result_dir: Path) -> None:
    """UI 벤치마크 화면이 --out 으로 다른 곳에 둔 결과도 찾게 $DUET_HOME/bench/index.json 에 적는다 (DESIGN.md 28.3)."""
    from duet.registry import duet_home

    path = duet_home() / "bench" / INDEX_FILE
    try:
        items = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
        items = [str(result_dir)] + [x for x in items if isinstance(x, str) and x != str(result_dir)]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items[:INDEX_MAX], ensure_ascii=False, indent=1), encoding="utf-8")
    except (OSError, ValueError):
        pass


def known_result_dirs() -> list[Path]:
    from duet.registry import duet_home

    base = duet_home() / "bench"
    found: set[Path] = set()
    if base.is_dir():
        found.update(p for p in base.iterdir() if (p / RESULTS_JSON).is_file())
        try:
            for x in json.loads((base / INDEX_FILE).read_text(encoding="utf-8")):
                if isinstance(x, str) and (Path(x) / RESULTS_JSON).is_file():
                    found.add(Path(x))
        except (OSError, ValueError):
            pass
    return sorted(found, key=lambda p: p.name, reverse=True)


def workflow_stats(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """워크플로별 요약 수치 (요약표·UI 벤치마크 화면이 함께 쓴다, DESIGN.md 20.4·28.3)."""
    out = []
    for w in dict.fromkeys(r["workflow"] for r in rows):
        rs = [r for r in rows if r["workflow"] == w]
        graded = [r for r in rs if r.get("hidden") and r["hidden"].get("total")]
        out.append({
            "workflow": w, "runs": len(rs), "approved": sum(1 for r in rs if r["approved"]),
            "arbiter": sum(1 for r in rs if r.get("arbiter") == "arbiter"),
            "hidden_rate": _mean([r["hidden"]["passed"] / r["hidden"]["total"] for r in graded]) * 100,
            "graded": len(graded), "all_passed": sum(1 for r in graded if r["hidden"]["all_passed"]),
            "missed": sum(1 for r in rs if r["approved"] and r.get("hidden") and not r["hidden"]["all_passed"]),
            "rounds": _mean([r.get("rounds") or 0 for r in rs]),
            "seconds": _mean([(r.get("seconds") or 0) - (r.get("limit_wait_sec") or 0) for r in rs]),
            "calls": _mean([r.get("calls") or 0 for r in rs]),
            "input": {a: _mean([((r.get("usage") or {}).get(a) or {}).get("input", 0) for r in rs]) for a in ("claude", "codex")},
            "output": _mean([sum(u.get("output", 0) for u in (r.get("usage") or {}).values()) for r in rs]),
            "codex_equiv": _mean([r.get("codex_equiv") or 0 for r in rs]),
            "max_input": {a: _mean([(r.get("max_input") or {}).get(a, 0) for r in rs]) for a in ("claude", "codex")},
            # 기록된 실행만 평균 (값이 없으면 None)
            "week_pct": {a: (_mean(vals) if vals else None) for a in ("claude", "codex")
                         for vals in [[(r.get("week_pct") or {}).get(a) for r in rs if (r.get("week_pct") or {}).get(a) is not None]]},
        })
    return out


def _pct(v: float | None) -> str:
    return "-" if v is None else f"{v:.1f}%p"


def summarize(data: dict[str, Any]) -> str:
    meta, rows = data.get("meta", {}), data.get("rows", [])
    lines = [f"# 벤치마크 결과 ({meta.get('started', '')})", "",
             f"과제 묶음 `{meta.get('suite')}`, 과제 {len(meta.get('tasks', []))}개, "
             f"반복 {meta.get('repeat')}회" + (", mock" if meta.get("mock") else "")
             + (", 고정 설계" if meta.get("fixed_design") else "") + f", 실행 {len(rows)}번", ""]
    workflows = list(dict.fromkeys(r["workflow"] for r in rows))
    lines += ["## 워크플로별", "",
              "| 워크플로 | 실행 | 승인 | 중재 승인 | 숨은 테스트 통과율 | 전부 통과 | 승인했는데 실패 | 평균 라운드 | 평균 시간 | 평균 호출 | 평균 입력 토큰 (Claude / Codex) | 평균 출력 토큰 | Codex 한도 환산 | 호출당 최대 입력 (Claude / Codex) | 주간 사용률 변화 (Claude / Codex) |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    del workflows
    for s in workflow_stats(rows):
        lines.append(
            f"| {s['workflow']} | {s['runs']} | {s['approved']}/{s['runs']} | {s['arbiter']} | "
            f"{s['hidden_rate']:.0f}% ({s['graded']}개 채점) | {s['all_passed']}/{s['graded']} | {s['missed']} | "
            f"{s['rounds']:.1f} | {_fmt_sec(s['seconds'])} | "
            f"{s['calls']:.1f} | {s['input']['claude']:,.0f} / {s['input']['codex']:,.0f} | {s['output']:,.0f} | "
            f"{s['codex_equiv']:,.0f} | {s['max_input']['claude']:,.0f} / {s['max_input']['codex']:,.0f} | "
            f"{_pct(s['week_pct']['claude'])} / {_pct(s['week_pct']['codex'])} |")
    lines += ["", "## 실행별", "", "| 과제 | 워크플로 | # | 결과 | 라운드 | 숨은 테스트 | 자체 테스트 | 시간 | 호출 | 입력 토큰 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        h = r.get("hidden")
        hidden = f"{h['passed']}/{h['total']}" if h else "-"
        tok = sum(u.get("input", 0) for u in (r.get("usage") or {}).values())
        lines.append(f"| {r['task']} | {r['workflow']} | {r['rep']} | {STATUS_KO.get(r['status'], r['status'])} | "
                     f"{r.get('rounds') or 0} | {hidden} | {r.get('own_tests') or '-'} | "
                     f"{_fmt_sec(r.get('seconds') or 0)} | {r.get('calls') or 0} | {tok:,} |")
    teams = [r for r in rows if r.get("team")]
    if teams:
        lines += ["", "## 분업", "", "| 과제 | 워크플로 | # | 묶음 | 구현한 묶음 | 되돌린 파일 | 계획 대체 |", "|---|---|---|---|---|---|---|"]
        for r in teams:
            t = r["team"]
            lines.append(f"| {r['task']} | {r['workflow']} | {r['rep']} | {t['packages']} | {t['parts_done']} | "
                         f"{t['reverted']} | {t['fallback'] or '-'} |")
    lines += ["", "- 숨은 테스트: 에이전트가 보지 못한 수용 테스트. 승인·미승인으로 끝난 실행만 채점한다.",
              "- Codex 한도 환산: 미캐시 입력 + 0.1×캐시 입력 + 5×출력 (요금표 비율). 주간 사용률 변화: 호출에 기록된 7일 창 "
              "사용률의 차이(앞 실행 마지막 값 기준, 같은 시간에 따로 쓴 양이 섞일 수 있음).",
              "- 승인했는데 실패: 리뷰가 승인했지만 숨은 테스트가 하나라도 실패한 실행 (리뷰가 놓친 결함)."]
    return "\n".join(lines) + "\n"


def load_results(result_dir: Path) -> dict[str, Any]:
    p = Path(result_dir).expanduser() / RESULTS_JSON
    if not p.is_file():
        raise BenchError(f"결과 파일이 없습니다: {p}")
    return json.loads(p.read_text(encoding="utf-8"))
