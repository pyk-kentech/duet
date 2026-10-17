"""관리자 UI 의 데이터·동작 계층. HTTP 와 분리해 단위 테스트할 수 있게 한다.

모든 경로 인자(project, run, file, commit)는 여기서 검증한다:
- project 는 등록된 작업 폴더여야 한다.
- run 은 그 폴더의 .duet/runs 아래 실제 실행이어야 한다.
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

from duet import procs, stopflag
from duet.activity import agent_activity, call_start_epoch
from duet.workflow import WorkflowError, list_workflows, load_workflow, role_agent_map
from duet.config import AGENT_NAMES, CLASSIC_WORKFLOW, WORKFLOW_NAME_RE, ConfigError, MAX_DEBATE_ROUNDS, MAX_REVIEW_ROUNDS, describe_effort, load_config
from duet.lock import read_lock
from duet.orchestrator import CONSOLE_LOG
from duet.phases.build import build_review_diff
from duet.phases.debate import BACKUP_FILENAME, DESIGN_FILENAME
from duet.doctor import ready, run_checks
from duet.registry import Registry, duet_home, normalize
from duet.runner import ExecutableNotFound, pid_alive, spawn_detached
from duet.usage import claude_local_usage, codex_rate_limits
from duet.state import DONE_UNAPPROVED, DUET_DIR, RUNNING, RunState, list_run_dirs
from duet.transcript import Transcript, split_header
from duet.verdict import parse_verdict
from duet.workspace import GitError, Workspace, WorkdirRefused, check_workdir

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
    """이 duet 를 다시 실행하는 명령. zip(duet.pyz)으로 돌고 있으면 그 파일을 실행한다."""
    import duet

    f = str(Path(duet.__file__))
    if ".pyz" in f:
        return [sys.executable, f[: f.index(".pyz") + 4]]
    return [sys.executable, "-m", "duet"]


def jobs_dir() -> Path:
    return duet_home() / "jobs"


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
            out.append({"path": p, "name": path.name or p, "exists": path.is_dir(),
                        "run_count": len(runs), "latest": latest, "live": self._live(path)})
        return out

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
        }

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
        if workflow and workflow != CLASSIC_WORKFLOW:
            if not WORKFLOW_NAME_RE.match(workflow):
                raise ApiError(400, f"워크플로 이름이 잘못되었습니다: {workflow}")
            overrides["workflow"] = workflow
        for key in ("implementer", "reviewer", "synth"):
            v = payload.get(key)
            if v and "workflow" not in overrides:
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
        if str(payload.get("test_command") or "").strip():
            overrides["test_command"] = str(payload["test_command"]).strip()
        if payload.get("block_severity"):
            overrides["block_severity"] = str(payload["block_severity"])
        if payload.get("stall_rounds") not in (None, ""):
            try:
                overrides["stall_rounds"] = int(payload["stall_rounds"])
            except (TypeError, ValueError):
                raise ApiError(400, "stall_rounds 는 숫자여야 합니다.") from None
        try:
            cfg = load_config(wd if wd.is_dir() else None, overrides)
        except ConfigError as e:
            raise ApiError(400, f"설정 오류: {e}") from e
        try:
            wf = load_workflow(cfg.workflow, wd if wd.is_dir() else None, cfg)
        except WorkflowError as e:
            raise ApiError(400, f"워크플로 오류: {e}") from e
        if design_only and wf.first("debate") is None:
            raise ApiError(400, f"워크플로 {wf.name} 에는 설계 단계가 없어 '설계만'을 고를 수 없습니다.")
        if skip_design and not (wd / DESIGN_FILENAME).is_file():
            raise ApiError(400, f"'설계 생략'인데 {wd / DESIGN_FILENAME} 이 없습니다.")
        self._ensure_not_busy(wd)

        wd.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        task_file = wd / DUET_DIR / UI_DIR / "tasks" / f"{stamp}.md"
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
        for on, flag in ((design_only, "--design-only"), (skip_design, "--skip-design"),
                         (mock, "--mock"), (force, "--force")):
            if on:
                argv.append(flag)
        self.registry.add(wd)
        return self._spawn("run", wd, argv)

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
            raise ApiError(409, "실행 중인 duet 가 없습니다.")
        if not _looks_like_duet(info.pid):
            raise ApiError(409, f"pid {info.pid} 가 duet 프로세스가 아닌 것 같아 중지하지 않았습니다.")
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
        log_dir = wd / DUET_DIR / UI_DIR / "jobs"
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
        }

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
                **{n: {"model": getattr(cfg, n).model,
                       "effort": "" if getattr(cfg, n).step_effort else getattr(cfg, n).effort,
                       "effort_label": describe_effort(getattr(cfg, n))} for n in ("claude", "codex")},
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
            "claude_local": claude_local_usage(),
            "duet": {"by_agent": by_agent, "by_day": dict(sorted(by_day.items(), reverse=True)[:14]),
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


def _looks_like_duet(pid: int) -> bool:
    return procs.looks_like_duet(pid)


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


# ====================================================================== API 메서드 표 (로컬 HTTP 와 원격 _api 가 같이 씀)
def _req(args: dict[str, Any], key: str) -> Any:
    return args.get(key)


API_METHODS: dict[str, Any] = {
    "projects": lambda d, a: {"projects": d.projects(), "jobs": d.jobs_list()},
    "add_project": lambda d, a: d.add_project(a.get("path")),
    "remove_project": lambda d, a: d.remove_project(a.get("project")),
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
    "stop": lambda d, a: d.stop(a),
    "usage": lambda d, a: d.usage_summary(),
    "activity": lambda d, a: d.activity(a.get("project"), a.get("run")),
    "doctor": lambda d, a: d.doctor(),
    "defaults": lambda d, a: d._defaults(None),
    "workflows": lambda d, a: d.workflows(a.get("project")),
}


def dispatch(d: Dashboard, method: str, args: dict[str, Any]) -> Any:
    fn = API_METHODS.get(method)
    if fn is None:
        raise ApiError(404, f"없는 API 입니다: {method}")
    return fn(d, args or {})
