"""관리자 UI 의 데이터·동작 계층. HTTP 와 분리해 단위 테스트할 수 있게 한다.

모든 경로 인자(project, run, file, commit)는 여기서 검증한다:
- project 는 등록된 작업 폴더여야 한다.
- run 은 그 폴더의 .tenure/runs 아래 실제 실행이어야 한다.
- file 은 그 실행의 기록 파일(NN_*.md) 이름이어야 한다.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import Popen
from typing import Any

from tenure.events import last_event, read_events
from tenure.outcome import run_activity
from tenure import procs, stopflag
from tenure.activity import agent_activity, call_start_epoch
from tenure.workflow import WorkflowError, list_workflows, load_workflow, role_agent_map
from tenure.config import AGENT_NAMES, CLASSIC_WORKFLOW, WORKFLOW_NAME_RE, ConfigError, MAX_DEBATE_ROUNDS, MAX_REVIEW_ROUNDS, describe_effort, load_config
from tenure.lock import read_lock
from tenure.orchestrator import CONSOLE_LOG
from tenure.phases.build import build_review_diff
from tenure.phases.debate import BACKUP_FILENAME, DESIGN_FILENAME
from tenure.doctor import ready, run_checks
from tenure.registry import Registry, tenure_home, normalize
from tenure.runner import ExecutableNotFound, pid_alive, spawn_detached
from tenure.agents.claude_code import load_claude_limits
from tenure.usage import claude_local_usage, codex_rate_limits
from tenure.state import DONE_APPROVED, DONE_UNAPPROVED, LEGACY_DIR, TENURE_DIR, RUNNING, RunState, list_run_dirs, project_dir
from tenure.transcript import Transcript, split_header
from tenure.verdict import parse_verdict
from tenure.workspace import GitError, Workspace, WorkdirRefused, check_workdir

RUN_ID_RE = re.compile(r"^\d{8}-\d{6}(?:-\d+)?$")
ENTRY_RE = re.compile(r"^\d{2,}_[\w.\-]+\.md$")
COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
MAX_DIFF_BYTES = 400_000
MAX_CONSOLE_CHUNK = 200_000
MAX_TASK_CHARS = 200_000
UI_DIR = "ui"


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def self_command() -> list[str]:
    """이 tenure 를 다시 실행하는 명령. zip(tenure.pyz)으로 돌고 있으면 그 파일을 실행한다."""
    import tenure

    f = str(Path(tenure.__file__))
    if ".pyz" in f:
        return [sys.executable, f[: f.index(".pyz") + 4]]
    return [sys.executable, "-m", "tenure"]


def jobs_dir() -> Path:
    return tenure_home() / "jobs"


def _read_job(path: Path) -> dict[str, Any] | None:
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rc_path = path.with_suffix(".rc")
    rc = None
    if rc_path.exists():
        try:
            rc = int(rc_path.read_text().strip())
        except (OSError, ValueError):
            rc = -1
    running = rc is None and pid_alive(int(rec.get("pid") or 0))
    if rc is None and not running:
        rc = -1  # 기록 없이 사라짐(강제 종료 등)
    try:
        tail = Path(rec["log_path"]).read_text(encoding="utf-8", errors="replace")[-4000:]
    except (OSError, KeyError):
        tail = ""
    return {**rec, "running": running, "returncode": rc, "log_tail": tail}


@dataclass
class Dashboard:
    registry: Registry = field(default_factory=Registry)
    _popens: list[Popen] = field(default_factory=list)   # 이 프로세스가 띄운 자식(좀비 방지용 reap)
    _jobs_lock: threading.Lock = field(default_factory=threading.Lock)
    _verdict_cache: dict[tuple[str, float], dict] = field(default_factory=dict)

    # ================================================================ validation
    def project(self, path: str | None) -> Path:
        if not path:
            raise ApiError(400, "project 가 필요합니다.")
        p = normalize(path)
        if p not in self.registry.list():
            # 등록하지 않는 벤치마크 실행도 알려진 결과 폴더 안이면 열 수 있다 (DESIGN.md 28.3)
            root = bench_root_of(Path(p))
            if root is None or root not in self.bench_dirs():
                raise ApiError(404, f"등록되지 않은 프로젝트입니다: {p}")
        return Path(p)

    def run_dir(self, project: Path, run_id: str | None) -> Path:
        if not run_id or not RUN_ID_RE.match(run_id):
            raise ApiError(400, "run 형식이 잘못되었습니다.")
        for d in list_run_dirs(project):
            if d.name == run_id:
                return d
        raise ApiError(404, f"실행을 찾을 수 없습니다: {run_id}")

    # ================================================================ projects
    def projects(self) -> list[dict[str, Any]]:
        self.reap()
        out = []
        for p in self.registry.list():
            path = Path(p)
            runs = list_run_dirs(path) if path.is_dir() else []
            latest = self._run_summary(path, runs[-1]) if runs else None
            bench = bench_root_of(path)
            out.append({"path": p, "name": path.name or p, "exists": path.is_dir(),
                        "bench": bench is not None, "bench_root": str(bench) if bench else None,
                        "run_count": len(runs), "latest": latest, "live": self._live(path)})
        _display_names(out)
        return out

    def prune_projects(self) -> dict[str, Any]:
        """폴더가 없는 프로젝트를 목록에서만 지운다 (DESIGN.md 28.2). 파일은 건드리지 않는다."""
        removed = [p for p in self.registry.list() if not Path(p).is_dir()]
        for p in removed:
            self.registry.remove(p)
        return {"removed": removed}

    # ================================================================ bench (DESIGN.md 28.3)
    def bench_dirs(self) -> list[Path]:
        from tenure.bench import known_result_dirs

        roots: set[Path] = set(known_result_dirs())
        for p in self.registry.list():
            b = bench_root_of(Path(p))
            if b is not None:
                roots.add(b)
        return sorted(roots, key=lambda p: p.name, reverse=True)

    def bench_list(self) -> dict[str, Any]:
        out = []
        for d in self.bench_dirs():
            try:
                data = json.loads((d / "results.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            meta, rows = data.get("meta") or {}, data.get("rows") or []
            out.append({"dir": str(d), "name": d.name, "suite": meta.get("suite"), "workflows": meta.get("workflows"),
                        "tasks": meta.get("tasks"), "repeat": meta.get("repeat"), "mock": meta.get("mock"),
                        "started": meta.get("started"), "runs": len(rows),
                        "approved": sum(1 for r in rows if r.get("approved")),
                        "all_passed": sum(1 for r in rows if (r.get("hidden") or {}).get("all_passed"))})
        return {"results": out}

    def bench_result(self, path: str | None) -> dict[str, Any]:
        allowed = {str(d): d for d in self.bench_dirs()}
        d = allowed.get(str(path or ""))
        if d is None:
            raise ApiError(404, "벤치마크 결과 폴더를 찾을 수 없습니다.")
        from tenure.bench import workflow_stats
        data = json.loads((d / "results.json").read_text(encoding="utf-8"))
        rows = data.get("rows") or []
        for r in rows:
            r["has_runs"] = bool(r.get("workdir")) and (Path(r["workdir"], TENURE_DIR, "runs").is_dir() or Path(r["workdir"], LEGACY_DIR, "runs").is_dir())
        return {"dir": str(d), "meta": data.get("meta") or {}, "rows": rows, "stats": workflow_stats(rows)}

    def add_project(self, path: str | None) -> dict[str, Any]:
        if not path or not str(path).strip():
            raise ApiError(400, "경로를 입력하세요.")
        raw = Path(str(path).strip()).expanduser()
        if not raw.is_absolute():
            raise ApiError(400, "절대 경로를 입력하세요 (예: /home/me/proj).")
        try:
            wd = check_workdir(raw, force=True)
        except WorkdirRefused as e:
            raise ApiError(400, str(e)) from e
        return {"path": self.registry.add(wd)}

    def remove_project(self, path: str | None) -> dict[str, Any]:
        p = self.project(path)
        self.registry.remove(p)
        return {"removed": str(p)}

    # ================================================================ runs
    def runs(self, project: str | None) -> dict[str, Any]:
        wd = self.project(project)
        runs = [self._run_summary(wd, d) for d in reversed(list_run_dirs(wd))]
        return {"project": str(wd), "live": self._live(wd), "runs": runs,
                "has_design": (wd / DESIGN_FILENAME).is_file(), "defaults": self._defaults(wd)}

    def run(self, project: str | None, run_id: str | None) -> dict[str, Any]:
        wd = self.project(project)
        rd = self.run_dir(wd, run_id)
        st = RunState.load(rd)
        live = self._live(wd)
        entries = []
        for e in Transcript(rd).entries():
            item: dict[str, Any] = {"name": e.name, "seq": e.seq, "label": e.label, "meta": e.meta}
            if e.meta.get("step") == "review" and e.meta.get("exit_code") == "0":
                item["verdict"] = self._verdict(e.path)
            entries.append(item)
        console = rd / CONSOLE_LOG
        return {
            "project": str(wd), "run_dir": str(rd), "state": st.to_dict(), "entries": entries,
            "live": bool(live and live.get("run_id") == st.run_id),
            "live_pid": live.get("pid") if live and live.get("run_id") == st.run_id else None,
            "stale": st.status == RUNNING and not (live and live.get("run_id") == st.run_id),
            "console_size": console.stat().st_size if console.is_file() else 0,
            "has_design_backup": (rd / BACKUP_FILENAME).is_file(),
            "current_call": self._current_call(rd) if live and live.get("run_id") == st.run_id else None,
            "resume": self._resume_hint(st, wd),
            "now": dt.datetime.now().isoformat(timespec="seconds"),
            "activity": self._activity(rd, st, bool(live and live.get("run_id") == st.run_id)),
            "last_seq": (last_event(rd) or {}).get("seq", 0),
        }

    def events(self, project: str | None, run_id: str | None, since: int = 0) -> dict[str, Any]:
        """seq 가 since 보다 큰 이벤트 (실시간 타임라인, DESIGN.md 36.3). SSE 가 없는 원격·브라우저는 이것으로 폴링."""
        wd = self.project(project)
        rd = self.run_dir(wd, run_id)
        evs = read_events(rd, since=int(since or 0))
        return {"events": evs, "last_seq": evs[-1]["seq"] if evs else int(since or 0)}

    def mark_seen(self, project: str | None, run_id: str | None) -> dict[str, Any]:
        """끝난 실행을 열어 봤다고 적는다(받은편지함에서 '끝났는데 안 봄'이 사라짐). 진행 중이면 그대로."""
        wd = self.project(project)
        rd = self.run_dir(wd, run_id)
        live = self._live(wd)
        if live and live.get("run_id") == rd.name:
            return {"ok": False, "reason": "진행 중"}
        st = RunState.load(rd)
        st.seen_at = dt.datetime.now().isoformat(timespec="seconds")
        st.save(rd)
        return {"ok": True, "seen_at": st.seen_at}

    def inbox(self, limit: int = 50, per_project: int = 20) -> dict[str, Any]:
        """프로젝트를 가로질러 주의 순으로: 나를 기다림 > 끝났는데 안 봄 > 진행 중 (DESIGN.md 36.7 받은편지함)."""
        items: list[dict[str, Any]] = []
        for proj in self.projects():
            path = proj.get("path") if isinstance(proj, dict) else None
            if not path or not proj.get("exists", True):
                continue
            wd = Path(path)
            for rd in list(reversed(list_run_dirs(wd)))[:per_project]:
                summary = self._run_summary(wd, rd)
                act = summary.get("activity") or {}
                if act.get("state") in ("blocked", "done-unseen", "working", "unverifiable") or (
                        act.get("state") == "failed" and summary.get("status") == RUNNING):
                    items.append({"project": str(wd), "run_id": summary["run_id"], "task": summary.get("task", "")[:200],
                                  "status": summary.get("status"), "activity": act,
                                  "updated_at": summary.get("updated_at")})
        items.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)   # 같은 순위 안에서는 최근 것 먼저
        items.sort(key=lambda x: -x["activity"].get("rank", 0))
        return {"items": items[:limit], "counts": {k: sum(1 for i in items if i["activity"]["state"] == k)
                                                    for k in ("blocked", "done-unseen", "working", "unverifiable")}}

    def activity(self, project: str | None, run_id: str | None) -> dict[str, Any]:
        """지금 진행 중인 호출에서 에이전트가 하는 일(파일 읽기·수정·명령·메시지)."""
        wd = self.project(project)
        rd = self.run_dir(wd, run_id)
        live = self._live(wd)
        if not live or live.get("run_id") != rd.name:
            return {"live": False, "call": None, "events": []}
        call = self._current_call(rd)
        if not call:
            return {"live": True, "call": None, "events": []}
        since = call_start_epoch(call["started"])
        return {"live": True, "call": call, "events": agent_activity(call["cli"], wd, since)}

    def _current_call(self, rd: Path) -> dict[str, Any] | None:
        """지금 호출. 로그에는 역할 이름이 찍히므로 세션 기록을 찾을 CLI 이름(cli)을 붙인다 (DESIGN.md 19.4)."""
        call = current_call(rd / CONSOLE_LOG)
        if call is None:
            return None
        try:
            roles = role_agent_map(RunState.load(rd).workflow)
        except (OSError, ValueError):
            roles = {}
        call["cli"] = roles.get(call["agent"], call["agent"])
        return call

    def workflows(self, project: str | None) -> dict[str, Any]:
        wd: Path | None = None
        if project:
            try:
                wd = self.project(project)
            except ApiError:
                wd = None
        try:
            cfg = load_config(wd)
        except ConfigError as e:
            return {"workflows": [], "default": CLASSIC_WORKFLOW, "error": str(e)}
        return {"workflows": list_workflows(wd, cfg), "default": cfg.workflow}

    def entry(self, project: str | None, run_id: str | None, name: str | None) -> dict[str, Any]:
        wd = self.project(project)
        rd = self.run_dir(wd, run_id)
        if not name or not ENTRY_RE.match(name) or not (rd / name).is_file():
            raise ApiError(404, "기록 파일을 찾을 수 없습니다.")
        meta, body = split_header((rd / name).read_text(encoding="utf-8", errors="replace"))
        return {"name": name, "meta": meta, "body": body}

    def console(self, project: str | None, run_id: str | None, offset: int = 0) -> dict[str, Any]:
        wd = self.project(project)
        rd = self.run_dir(wd, run_id)
        path = rd / CONSOLE_LOG
        if not path.is_file():
            return {"text": "", "offset": 0, "size": 0}
        size = path.stat().st_size
        offset = max(0, min(int(offset), size))
        if size - offset > MAX_CONSOLE_CHUNK:
            offset = size - MAX_CONSOLE_CHUNK
        with path.open("rb") as f:
            f.seek(offset)
            data = f.read(MAX_CONSOLE_CHUNK)
        return {"text": data.decode("utf-8", errors="replace"), "offset": offset + len(data), "size": size}

    def design(self, project: str | None, run_id: str | None = None, which: str = "current") -> dict[str, Any]:
        wd = self.project(project)
        if which == "backup":
            rd = self.run_dir(wd, run_id)
            path = rd / BACKUP_FILENAME
        else:
            # 변경 설계로 끝난 실행은 그 실행의 docs/changes/<run>.md (DESIGN.md 19.5)
            doc = RunState.load(self.run_dir(wd, run_id)).design_doc if run_id else None
            path = wd / (doc or DESIGN_FILENAME)
        if not path.is_file():
            return {"text": None, "path": str(path)}
        return {"text": path.read_text(encoding="utf-8", errors="replace"), "path": str(path)}

    # ================================================================ git
    def commits(self, project: str | None, run_id: str | None) -> dict[str, Any]:
        wd = self.project(project)
        st = RunState.load(self.run_dir(wd, run_id))
        ws = Workspace(wd)
        if not st.base_commit or not ws.is_repo():
            return {"base": None, "commits": []}
        try:
            fmt = "%H%x1f%h%x1f%s%x1f%cI"
            out = ws.git("log", f"--format={fmt}", f"{st.base_commit}^!", "--")
            out += ws.git("log", "--reverse", f"--format={fmt}", f"{st.base_commit}..HEAD", "--")
        except GitError as e:
            raise ApiError(500, str(e)) from e
        commits = []
        for line in out.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 4:
                commits.append({"sha": parts[0], "short": parts[1], "subject": parts[2], "date": parts[3]})
        return {"base": st.base_commit, "commits": commits}

    def diff(self, project: str | None, run_id: str | None, commit: str | None = None) -> dict[str, Any]:
        wd = self.project(project)
        st = RunState.load(self.run_dir(wd, run_id))
        ws = Workspace(wd)
        if not st.base_commit or not ws.is_repo():
            return {"text": "", "truncated": False, "title": "아직 커밋이 없습니다."}
        try:
            if commit:
                if not COMMIT_RE.match(commit):
                    raise ApiError(400, "commit 형식이 잘못되었습니다.")
                if ws.git("cat-file", "-t", commit, check=False).strip() != "commit":
                    raise ApiError(404, "커밋을 찾을 수 없습니다.")
                text = ws.git("show", "--no-color", "--format=commit %H%n%s%n", commit)
                title = f"커밋 {commit[:7]}"
            else:
                try:
                    globs = load_config(wd).diff_excludes
                except ConfigError:
                    globs = []
                text = build_review_diff(ws, st.base_commit, globs, MAX_DIFF_BYTES * 2)
                if text == "(변경 없음)":
                    text = ""
                title = f"기준 {st.base_commit} 대비 전체 변경 (리뷰어가 받는 diff 와 같은 규칙: DESIGN.md·잠금 파일 제외)"
        except GitError as e:
            raise ApiError(500, str(e)) from e
        truncated = len(text) > MAX_DIFF_BYTES
        return {"text": text[:MAX_DIFF_BYTES], "truncated": truncated, "title": title}

    # ================================================================ actions
    def start_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = str(payload.get("task") or "").strip()
        if not task:
            raise ApiError(400, "과제를 입력하세요.")
        if len(task) > MAX_TASK_CHARS:
            raise ApiError(400, "과제가 너무 깁니다.")
        raw = str(payload.get("project") or "").strip()
        if not raw or not Path(raw).expanduser().is_absolute():
            raise ApiError(400, "작업 폴더는 절대 경로여야 합니다.")
        design_only, skip_design = bool(payload.get("design_only")), bool(payload.get("skip_design"))
        mock, force = bool(payload.get("mock")), bool(payload.get("force"))
        if design_only and skip_design:
            raise ApiError(400, "'설계만'과 '설계 생략'은 함께 고를 수 없습니다.")
        try:
            wd = check_workdir(Path(raw), force=force, allow=(DESIGN_FILENAME,) if skip_design else ())
        except WorkdirRefused as e:
            raise ApiError(400, str(e)) from e
        overrides: dict[str, Any] = {}
        workflow = str(payload.get("workflow") or "").strip()
        if workflow:                                   # classic 도 명시해서 넘긴다(기본이 auto 라서, 36.5)
            if not WORKFLOW_NAME_RE.match(workflow):
                raise ApiError(400, f"워크플로 이름이 잘못되었습니다: {workflow}")
            overrides["workflow"] = workflow
        for key in ("implementer", "reviewer", "synth"):
            v = payload.get(key)
            if v and overrides.get("workflow", CLASSIC_WORKFLOW) == CLASSIC_WORKFLOW:
                if v not in AGENT_NAMES:
                    raise ApiError(400, f"{key} 값이 잘못되었습니다: {v}")
                overrides[key] = v
        for key in ("debate_rounds", "max_review"):
            v = payload.get(key)
            if v not in (None, ""):
                try:
                    overrides[key] = int(v)
                except (TypeError, ValueError):
                    raise ApiError(400, f"{key} 는 숫자여야 합니다.") from None
        for agent in AGENT_NAMES:
            for field_ in ("model", "effort"):
                v = payload.get(f"{agent}_{field_}")
                if v not in (None, ""):
                    overrides[f"{agent}.{field_}"] = str(v).strip()
        step_items = self._step_items(payload.get("step_overrides"))
        if step_items:
            from tenure.config import parse_set_step

            try:
                overrides["step_overrides"] = parse_set_step(step_items)
            except ConfigError as e:
                raise ApiError(400, f"설정 오류: {e}") from e
        if str(payload.get("test_command") or "").strip():
            overrides["test_command"] = str(payload["test_command"]).strip()
        if payload.get("block_severity"):
            overrides["block_severity"] = str(payload["block_severity"])
        if payload.get("stall_rounds") not in (None, ""):
            try:
                overrides["stall_rounds"] = int(payload["stall_rounds"])
            except (TypeError, ValueError):
                raise ApiError(400, "stall_rounds 는 숫자여야 합니다.") from None
        from tenure.options import OptionError, clean as clean_options, to_cli

        try:
            advanced = clean_options(payload.get("options") or {})   # 고급 설정 (DESIGN.md 28.4)
        except OptionError as e:
            raise ApiError(400, str(e)) from e
        advanced = {k: v for k, v in advanced.items() if k not in overrides}
        overrides.update(advanced)
        try:
            cfg = load_config(wd if wd.is_dir() else None, overrides)
        except ConfigError as e:
            raise ApiError(400, f"설정 오류: {e}") from e
        # auto 는 실행할 때 과제를 보고 고른다(36.5). 여기서는 classic 으로 미리 확인해 둔다(설계만 등)
        check_name = CLASSIC_WORKFLOW if cfg.workflow == "auto" else cfg.workflow
        try:
            wf = load_workflow(check_name, wd if wd.is_dir() else None, cfg)
        except WorkflowError as e:
            raise ApiError(400, f"워크플로 오류: {e}") from e
        unknown = sorted(set(cfg.step_overrides) - set(wf.roles))
        if unknown:
            raise ApiError(400, f"칸 단위 지정의 역할 {', '.join(unknown)} 이 워크플로 {wf.name} 에 없습니다.")
        if design_only and wf.first("debate") is None:
            raise ApiError(400, f"워크플로 {wf.name} 에는 설계 단계가 없어 '설계만'을 고를 수 없습니다.")
        if skip_design and not (wd / DESIGN_FILENAME).is_file():
            raise ApiError(400, f"'설계 생략'인데 {wd / DESIGN_FILENAME} 이 없습니다.")
        self._ensure_not_busy(wd)

        uploads = self._decode_attachments(payload.get("attachments"))
        wd.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        attach_paths = []
        if uploads:
            adir = project_dir(wd) / UI_DIR / "attachments" / stamp
            adir.mkdir(parents=True, exist_ok=True)
            for name, data in uploads:
                target = adir / name
                n = 2
                while target.exists():
                    target = adir / f"{Path(name).stem}-{n}{Path(name).suffix}"
                    n += 1
                target.write_bytes(data)
                attach_paths.append(target)
        task_file = project_dir(wd) / UI_DIR / "tasks" / f"{stamp}.md"
        task_file.parent.mkdir(parents=True, exist_ok=True)
        task_file.write_text(task, encoding="utf-8")

        argv = ["run", f"@{task_file}", "--workdir", str(wd)]
        for key, flag in (("workflow", "--workflow"), ("implementer", "--implementer"), ("reviewer", "--reviewer"), ("synth", "--synth"),
                          ("debate_rounds", "--debate-rounds"), ("max_review", "--max-review"),
                          ("claude.model", "--claude-model"), ("claude.effort", "--claude-effort"),
                          ("codex.model", "--codex-model"), ("codex.effort", "--codex-effort"),
                          ("test_command", "--test-command"), ("block_severity", "--block-severity"),
                          ("stall_rounds", "--stall-rounds")):
            if key in overrides:
                argv += [flag, str(overrides[key])]
        for key, value in advanced.items():
            argv += ["--set", f"{key}={to_cli(value)}"]
        for item in step_items:
            argv += ["--set-step", item]
        for p in attach_paths:
            argv += ["--attach", str(p)]
        for on, flag in ((design_only, "--design-only"), (skip_design, "--skip-design"),
                         (mock, "--mock"), (force, "--force")):
            if on:
                argv.append(flag)
        self.registry.add(wd)
        return self._spawn("run", wd, argv)

    @staticmethod
    def _decode_attachments(raw: Any) -> list[tuple[str, bytes]]:
        """UI 가 보낸 [{name, data(base64)}] → [(안전한 이름, 바이트)] (DESIGN.md 33.3)"""
        import base64
        import binascii

        from tenure.attachments import MAX_FILES, MAX_TOTAL_BYTES, safe_name

        if raw in (None, "", []):
            return []
        if not isinstance(raw, list) or len(raw) > MAX_FILES:
            raise ApiError(400, f"첨부는 {MAX_FILES}개까지입니다.")
        out, total = [], 0
        for item in raw:
            if not isinstance(item, dict) or not isinstance(item.get("data"), str):
                raise ApiError(400, "첨부 형식이 잘못되었습니다.")
            try:
                data = base64.b64decode(item["data"], validate=True)
            except (binascii.Error, ValueError):
                raise ApiError(400, f"첨부를 읽을 수 없습니다: {item.get('name')}") from None
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise ApiError(400, f"첨부는 합쳐서 {MAX_TOTAL_BYTES // (1024 * 1024)}MB 까지입니다.")
            out.append((safe_name(str(item.get("name") or "file")), data))
        return out

    @staticmethod
    def _step_items(raw: Any) -> list[str]:
        """UI 의 {역할: {단계: {model, effort}}} → ["역할.단계.model=값", ...] (검증은 parse_set_step·Config.validate)"""
        if raw in (None, "", {}):
            return []
        if not isinstance(raw, dict):
            raise ApiError(400, "step_overrides 는 객체여야 합니다.")
        items: list[str] = []
        for role, steps in raw.items():
            if not isinstance(steps, dict):
                raise ApiError(400, f"step_overrides.{role} 는 객체여야 합니다.")
            for step, vals in steps.items():
                if not isinstance(vals, dict):
                    raise ApiError(400, f"step_overrides.{role}.{step} 는 객체여야 합니다.")
                for k, v in vals.items():
                    v = str(v or "").strip()
                    if v:
                        if any(c in f"{role}{step}{k}" for c in ".="):
                            raise ApiError(400, "step_overrides 의 이름에 '.' 이나 '=' 를 쓸 수 없습니다.")
                        items.append(f"{role}.{step}.{k}={v}")
        return items

    def make_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        """끝난 실행의 결과 요약을 작업으로 만든다 (DESIGN.md 32.3)."""
        wd = self.project(payload.get("project"))
        rd = self.run_dir(wd, payload.get("run"))
        st = RunState.load(rd)
        if st.status not in (DONE_APPROVED, DONE_UNAPPROVED):
            raise ApiError(400, "승인·미승인으로 끝난 실행만 요약할 수 있습니다.")
        self._ensure_not_busy(wd)
        argv = ["report", "--workdir", str(wd), "--run", rd.name]
        if st.config.get("mock"):
            argv.append("--mock")
        return self._spawn("report", wd, argv)

    def resume(self, payload: dict[str, Any]) -> dict[str, Any]:
        wd = self.project(payload.get("project"))
        rd = self.run_dir(wd, payload.get("run"))
        argv = ["resume", "--workdir", str(wd), "--run", rd.name]
        mr = payload.get("max_review")
        if mr not in (None, ""):
            try:
                mr = int(mr)
            except (TypeError, ValueError):
                raise ApiError(400, "max_review 는 숫자여야 합니다.") from None
            if not 1 <= mr <= MAX_REVIEW_ROUNDS:
                raise ApiError(400, f"max_review 는 1~{MAX_REVIEW_ROUNDS} 사이여야 합니다.")
            argv += ["--max-review", str(mr)]
        st = RunState.load(rd)
        hint = self._resume_hint(st, wd)
        if not hint["possible"]:
            raise ApiError(400, hint["reason"])
        if hint["needs_max_review"] and (mr in (None, "") or int(mr) <= hint["current_max_review"]):
            raise ApiError(400, f"리뷰 상한을 {hint['current_max_review']}보다 크게 지정하세요.")
        self._ensure_not_busy(wd)
        return self._spawn("resume", wd, argv)

    def stop(self, payload: dict[str, Any]) -> dict[str, Any]:
        wd = self.project(payload.get("project"))
        info = read_lock(wd)
        if info is None:
            raise ApiError(409, "실행 중인 tenure 가 없습니다.")
        if not _looks_like_tenure(info.pid):
            raise ApiError(409, f"pid {info.pid} 가 tenure 프로세스가 아닌 것 같아 중지하지 않았습니다.")
        if payload.get("force"):
            # 정상 중지가 듣지 않을 때. 상태는 running 으로 남아 UI 가 '멈춤'으로 보이고 resume 할 수 있다
            procs.kill_pid_tree(info.pid)
            return {"stopped": info.pid, "run_id": info.run_id, "method": "force"}
        stopflag.request(wd)                      # 모든 OS (DESIGN.md 27.3)
        signaled = procs.terminate_pid(info.pid)  # POSIX 는 SIGTERM 도 (더 빠르다)
        return {"stopped": info.pid, "run_id": info.run_id, "method": "signal" if signaled else "request"}

    def jobs_list(self, limit: int = 20) -> list[dict[str, Any]]:
        self.reap()
        d = jobs_dir()
        if not d.is_dir():
            return []
        out = []
        for path in sorted(d.glob("*.json"), reverse=True)[:limit]:
            rec = _read_job(path)
            if rec:
                out.append(rec)
        return out

    def reap(self) -> None:
        with self._jobs_lock:
            self._popens = [p for p in self._popens if p.poll() is None]

    # ================================================================ helpers
    def _spawn(self, kind: str, wd: Path, argv: list[str]) -> dict[str, Any]:
        log_dir = project_dir(wd) / UI_DIR / "jobs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        job_id = f"{stamp}-{kind}"
        log_path = log_dir / f"{job_id}.log"
        rec_dir = jobs_dir()
        rec_dir.mkdir(parents=True, exist_ok=True)
        rec_path = rec_dir / f"{job_id}.json"
        # _job 래퍼가 끝날 때 종료 코드를 .rc 에 남긴다(UI 를 다시 켜거나 원격에서도 결과를 알 수 있게)
        cmd = [*self_command(), "_job", str(rec_path.with_suffix(".rc")), "--", *argv]
        try:
            with log_path.open("ab") as log_file:
                popen = spawn_detached(cmd, wd, log_file=log_file, env={"PYTHONUNBUFFERED": "1"})
        except ExecutableNotFound as e:
            raise ApiError(500, str(e)) from e
        rec = {"id": job_id, "kind": kind, "project": str(wd), "argv": argv, "pid": popen.pid,
               "log_path": str(log_path), "started_at": dt.datetime.now().isoformat(timespec="seconds")}
        rec_path.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        with self._jobs_lock:
            self._popens.append(popen)
        return _read_job(rec_path) or {**rec, "running": True, "returncode": None, "log_tail": ""}

    def _ensure_not_busy(self, wd: Path) -> None:
        info = read_lock(wd)
        if info is not None:
            raise ApiError(409, f"이 작업 폴더에서 이미 실행 중입니다 (pid {info.pid}, 실행 {info.run_id}).")
        for j in self.jobs_list(limit=50):
            if j.get("project") == str(wd) and j["running"]:
                raise ApiError(409, "이 작업 폴더에서 UI 가 시작한 실행이 아직 끝나지 않았습니다.")

    def _live(self, wd: Path) -> dict[str, Any] | None:
        info = read_lock(wd)
        if info is None:
            return None
        return {"pid": info.pid, "run_id": info.run_id, "started_at": info.started_at}

    def _run_summary(self, wd: Path, rd: Path) -> dict[str, Any]:
        try:
            st = RunState.load(rd)
        except (OSError, ValueError, TypeError) as e:
            return {"run_id": rd.name, "status": "broken", "error": str(e)}
        live = self._live(wd)
        is_live = bool(live and live.get("run_id") == st.run_id)
        return {
            "run_id": st.run_id, "status": st.status, "phase": st.phase, "step": st.step, "round": st.round,
            "task": st.task[:300], "created_at": st.created_at, "updated_at": st.updated_at,
            "calls": len(st.calls), "total_sec": round(sum(c.sec for c in st.calls), 1),
            "last_verdict": st.last_verdict, "config": st.config, "error": st.error,
            "live": is_live, "stale": st.status == RUNNING and not is_live,
            "activity": self._activity(rd, st, is_live),
        }

    def _activity(self, rd: Path, st: RunState, is_live: bool) -> dict[str, Any]:
        """화면이 정렬·표시할 활동 상태 (DESIGN.md 36.3.1)."""
        ev = last_event(rd)
        return run_activity(st.to_dict(), live=is_live, last_ts=(ev or {}).get("ts") or st.updated_at, legacy=ev is None)

    def _resume_hint(self, st: RunState, wd: Path) -> dict[str, Any]:
        cur = int(st.config.get("max_review") or 0)
        if st.status == DONE_UNAPPROVED and st.stop_reason in ("stalled", "arbiter_final") and st.round < cur:
            live = self._live(wd)
            if live and live.get("run_id") == st.run_id:
                return {"possible": False, "needs_max_review": False, "current_max_review": cur, "reason": "지금 실행 중입니다."}
            return {"possible": True, "needs_max_review": False, "current_max_review": cur, "reason": ""}
        if st.status == DONE_UNAPPROVED:
            return {"possible": cur < MAX_REVIEW_ROUNDS, "needs_max_review": True, "current_max_review": cur,
                    "reason": "리뷰 상한이 최대치입니다." if cur >= MAX_REVIEW_ROUNDS else ""}
        if st.finished:
            return {"possible": False, "needs_max_review": False, "current_max_review": cur,
                    "reason": "이미 끝난 실행입니다."}
        live = self._live(wd)
        if live and live.get("run_id") == st.run_id:
            return {"possible": False, "needs_max_review": False, "current_max_review": cur,
                    "reason": "지금 실행 중입니다."}
        return {"possible": True, "needs_max_review": False, "current_max_review": cur, "reason": ""}

    def _defaults(self, wd: Path | None) -> dict[str, Any]:
        try:
            cfg = load_config(wd if wd is not None and wd.is_dir() else None)
        except ConfigError as e:
            return {"error": str(e)}
        return {"workflow": cfg.workflow, "implementer": cfg.implementer, "reviewer": cfg.reviewer,
                "synth": cfg.synth_name,
                "debate_rounds": cfg.debate_rounds, "max_review": cfg.max_review,
                # 단계별 강도가 있으면 effort 를 비워 둔다: 화면이 그 값을 다시 넘기면 단계별 설정이 지워진다
                # 단계별 모델이 있으면 model 도 비워 둔다(같은 이유, DESIGN.md 30.2)
                **{n: {"model": "" if getattr(cfg, n).step_model else getattr(cfg, n).model,
                       "model_base": getattr(cfg, n).model, "step_model": dict(getattr(cfg, n).step_model),
                       "effort": "" if getattr(cfg, n).step_effort else getattr(cfg, n).effort,
                       "effort_label": describe_effort(getattr(cfg, n)),
                       # 순서도용 실제 값 (effort 칸은 위처럼 비워 두지만 그림에는 단계별 강도를 보인다)
                       "effort_base": getattr(cfg, n).effort, "step_effort": dict(getattr(cfg, n).step_effort)}
                   for n in ("claude", "codex")},
                "test_command": cfg.test_command, "block_severity": cfg.block_severity,
                "stall_rounds": cfg.stall_rounds, "require_tests_pass": cfg.require_tests_pass,
                "review_diff": cfg.review_diff, "repro_tests": cfg.repro_tests,
                "limits": {"debate_rounds": MAX_DEBATE_ROUNDS, "max_review": MAX_REVIEW_ROUNDS}}

    # ================================================================ usage
    def usage_summary(self) -> dict[str, Any]:
        projects = []
        by_agent: dict[str, dict] = {}
        by_day: dict[str, dict[str, dict]] = {}
        for p in self.registry.list():
            wd = Path(p)
            if not wd.is_dir():
                continue
            proj_total: dict[str, dict] = {}
            for rd in list_run_dirs(wd):
                try:
                    st = RunState.load(rd)
                except (OSError, ValueError, TypeError):
                    continue
                day = (st.created_at or "")[:10]
                for agent, u in st.usage_totals().items():
                    for bucket in (proj_total.setdefault(agent, {}), by_agent.setdefault(agent, {}),
                                   by_day.setdefault(day, {}).setdefault(agent, {})):
                        for k, v in u.items():
                            bucket[k] = round(bucket.get(k, 0) + v, 4) if isinstance(v, float) else bucket.get(k, 0) + v
            if proj_total:
                projects.append({"path": p, "name": wd.name, "by_agent": proj_total})
        return {
            "codex_limits": codex_rate_limits(),
            "claude_limits": load_claude_limits(),     # tenure 가 Claude 를 부를 때 갱신 (DESIGN.md 28.6)
            "claude_local": claude_local_usage(),
            "tenure": {"by_agent": by_agent, "by_day": dict(sorted(by_day.items(), reverse=True)[:14]),
                     "projects": projects},
        }

    def doctor(self) -> dict[str, Any]:
        checks = run_checks()
        return {"checks": checks, "ready": ready(checks)}

    def _verdict(self, path: Path) -> dict[str, Any]:
        key = (str(path), path.stat().st_mtime)
        if key not in self._verdict_cache:
            v = parse_verdict(split_header(path.read_text(encoding="utf-8", errors="replace"))[1])
            self._verdict_cache[key] = {"status": v.status.value, "must_fix": v.must_fix, "source": v.source,
                                        "parse_failed": v.parse_failed, "contradiction": v.contradiction}
        return self._verdict_cache[key]


def _looks_like_tenure(pid: int) -> bool:
    return procs.looks_like_tenure(pid)


def bench_root_of(path: Path) -> Path | None:
    """벤치마크 실행의 작업 폴더(<결과>/<과제>/<워크플로-반복>)면 결과 폴더 (DESIGN.md 28.2)."""
    root = path.parent.parent
    return root if (root / "results.json").is_file() else None


def _display_names(items: list[dict[str, Any]]) -> None:
    """이름이 같으면 부모 폴더 이름을 붙여 구별한다(ledger / lean-1). Windows 경로도 Path 로 다룬다."""
    counts: dict[str, int] = {}
    for it in items:
        counts[it["name"]] = counts.get(it["name"], 0) + 1
    for it in items:
        parent = Path(it["path"]).parent.name
        it["display"] = f"{parent} / {it['name']}" if counts[it["name"]] > 1 and parent else it["name"]


_CALL_START_RE = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\] (\w+) ← (\w+)(?: \(재시도 (\d+)\))? 실행 중")
_CALL_END_RE = re.compile(r"^\[\d{2}:\d{2}:\d{2}\] (\w+) ← (\w+)(?: \(재시도 \d+\))? (완료|실패)")


def current_call(console: Path, now: dt.datetime | None = None) -> dict[str, Any] | None:
    """console.log 끝부분에서 '지금 진행 중인 호출'을 찾는다."""
    try:
        with console.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 16_384))
            tail = f.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(tail):
        if _CALL_END_RE.match(line):
            return None
        m = _CALL_START_RE.match(line)
        if m:
            hh, mm, ss, agent, step, retry = m.groups()
            now = now or dt.datetime.now()
            started = now.replace(hour=int(hh), minute=int(mm), second=int(ss), microsecond=0)
            elapsed = (now - started).total_seconds()
            if elapsed < 0:  # 자정을 넘김
                elapsed += 86_400
            return {"agent": agent, "step": step, "retry": int(retry or 0),
                    "started": f"{hh}:{mm}:{ss}", "elapsed_sec": int(elapsed)}
    return None


# ====================================================================== 폴더 고르기 (DESIGN.md 28.9)
FS_MAX_ENTRIES = 500
_FILE_ATTRIBUTE_HIDDEN, _FILE_ATTRIBUTE_SYSTEM = 0x2, 0x4


def _fs_roots() -> list[dict[str, str]]:
    roots = [{"name": "홈", "path": str(Path.home())}]
    if os.name == "nt":
        import string

        roots += [{"name": f"{c}:", "path": f"{c}:\\"} for c in string.ascii_uppercase if os.path.isdir(f"{c}:\\")]
    else:
        roots.append({"name": "/", "path": "/"})
    return roots


def _visible_dir(entry: os.DirEntry) -> bool:
    if entry.name.startswith(".") or entry.name.startswith("$"):
        return False
    try:
        if not entry.is_dir(follow_symlinks=True):
            return False
        attrs = getattr(entry.stat(follow_symlinks=True), "st_file_attributes", 0)
    except OSError:
        return False
    return not attrs & (_FILE_ATTRIBUTE_HIDDEN | _FILE_ATTRIBUTE_SYSTEM)


def list_dirs(path: Any) -> dict[str, Any]:
    """폴더 고르기 창용: 하위 폴더 이름만 (파일 내용은 읽지 않는다)."""
    raw = str(path or "").strip()
    base = {"roots": _fs_roots(), "sep": os.sep, "home": str(Path.home())}
    if not raw:
        return {**base, "path": None, "parent": None, "entries": [], "truncated": False}
    p = Path(raw).expanduser()
    if not p.is_absolute():
        raise ApiError(400, f"절대 경로여야 합니다: {raw}")
    try:
        p = p.resolve()
    except OSError:
        pass
    if not p.is_dir():
        raise ApiError(404, f"없는 폴더입니다: {p}")
    try:
        with os.scandir(p) as it:
            found = [e for e in it if _visible_dir(e)]
    except OSError as e:
        raise ApiError(403, f"열 수 없는 폴더입니다: {p} ({e.strerror or e})") from None
    found.sort(key=lambda e: e.name.lower())
    entries = []
    for e in found[:FS_MAX_ENTRIES]:
        full = Path(e.path)
        entries.append({"name": e.name, "path": str(full), "git": (full / ".git").exists(),
                        "tenure": (full / TENURE_DIR).is_dir() or (full / LEGACY_DIR).is_dir()})
    parent = str(p.parent) if p.parent != p else None
    return {**base, "path": str(p), "parent": parent, "entries": entries, "truncated": len(found) > FS_MAX_ENTRIES}


# ====================================================================== API 메서드 표 (로컬 HTTP 와 원격 _api 가 같이 씀)
def _req(args: dict[str, Any], key: str) -> Any:
    return args.get(key)


API_METHODS: dict[str, Any] = {
    "projects": lambda d, a: {"projects": d.projects(), "jobs": d.jobs_list()},
    "add_project": lambda d, a: d.add_project(a.get("path")),
    "remove_project": lambda d, a: d.remove_project(a.get("project")),
    "prune_projects": lambda d, a: d.prune_projects(),
    "bench_list": lambda d, a: d.bench_list(),
    "bench_result": lambda d, a: d.bench_result(a.get("dir")),
    "runs": lambda d, a: d.runs(a.get("project")),
    "run": lambda d, a: d.run(a.get("project"), a.get("run")),
    "entry": lambda d, a: d.entry(a.get("project"), a.get("run"), a.get("file")),
    "console": lambda d, a: d.console(a.get("project"), a.get("run"), int(a.get("offset") or 0)),
    "design": lambda d, a: d.design(a.get("project"), a.get("run"), a.get("which") or "current"),
    "commits": lambda d, a: d.commits(a.get("project"), a.get("run")),
    "diff": lambda d, a: d.diff(a.get("project"), a.get("run"), a.get("commit") or None),
    "jobs": lambda d, a: {"jobs": d.jobs_list()},
    "start_run": lambda d, a: d.start_run(a),
    "resume": lambda d, a: d.resume(a),
    "make_report": lambda d, a: d.make_report(a),
    "stop": lambda d, a: d.stop(a),
    "usage": lambda d, a: d.usage_summary(),
    "activity": lambda d, a: d.activity(a.get("project"), a.get("run")),
    "doctor": lambda d, a: d.doctor(),
    "defaults": lambda d, a: d._defaults(None),
    "workflows": lambda d, a: d.workflows(a.get("project")),
    "list_dirs": lambda d, a: list_dirs(a.get("path")),
    "events": lambda d, a: d.events(a.get("project"), a.get("run"), int(a.get("since") or 0)),
    "mark_seen": lambda d, a: d.mark_seen(a.get("project"), a.get("run")),
    "inbox": lambda d, a: d.inbox(),
}


def dispatch(d: Dashboard, method: str, args: dict[str, Any]) -> Any:
    fn = API_METHODS.get(method)
    if fn is None:
        raise ApiError(404, f"없는 API 입니다: {method}")
    return fn(d, args or {})
