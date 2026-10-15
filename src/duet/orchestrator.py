"""Orchestrator — 단계 진행과 resume.

check() 두 어댑터
DebatePhase (skip-design 아니면) → design-only 면 종료
BuildPhase
각 스텝 직후 RunState 저장. resume 은 마지막 run 의 완료 스텝 다음부터 이어간다.

실행 중에는 <workdir>/.duet/lock.json 으로 같은 폴더의 동시 실행을 막고,
진행 로그를 터미널과 <run_dir>/console.log 에 함께 남긴다(UI 가 실시간으로 읽는다).
"""

from __future__ import annotations

import datetime as dt
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Callable, Mapping

from duet.agents import AgentAdapter, AgentNotAvailable, make_agents
from duet.config import Config, ConfigError, load_config
from duet.lock import LockBusy, RunLock
from duet.phases.build import BuildPhase
from duet.phases.common import PhaseContext, PhaseStop
from duet.phases.debate import DESIGN_FILENAME, DebatePhase
from duet.registry import register_quietly
from duet.state import (
    DONE_APPROVED,
    DONE_DESIGN,
    DONE_UNAPPROVED,
    FAILED,
    PHASE_DONE,
    RUNNING,
    STOPPED_RATE_LIMIT,
    STOPPED_USER,
    RunState,
    create_run_dir,
    latest_run_dir,
    list_run_dirs,
)
from duet.transcript import Transcript
from duet.workspace import GitError, WorkdirRefused, check_workdir

Printer = Callable[[str], None]

CONFIG_KEYS = ("implementer", "reviewer", "synth", "debate_rounds", "max_review",
               "claude.model", "claude.effort", "codex.model", "codex.effort")
CONSOLE_LOG = "console.log"

EXIT_OK = 0
EXIT_UNAPPROVED = 1
EXIT_STOPPED = 3
EXIT_INTERRUPTED = 130


class OrchestratorError(Exception):
    """사용자에게 그대로 보여줄 오류."""


@dataclass
class RunOptions:
    task: str
    workdir: Path
    design_only: bool = False
    skip_design: bool = False
    mock: bool = False
    force: bool = False
    overrides: dict[str, Any] = field(default_factory=dict)   # CONFIG_KEYS 중 CLI 로 지정된 것


@dataclass
class RunOutcome:
    state: RunState
    run_dir: Path
    stop: PhaseStop | None = None

    @property
    def exit_code(self) -> int:
        s = self.state.status
        if s in (DONE_APPROVED, DONE_DESIGN):
            return EXIT_OK
        if s == DONE_UNAPPROVED:
            return EXIT_UNAPPROVED
        if s == STOPPED_USER:
            return EXIT_INTERRUPTED
        return EXIT_STOPPED


def default_printer(line: str) -> None:
    print(line, flush=True)


class Orchestrator:
    def __init__(self, printer: Printer = default_printer,
                 agent_factory: Callable[..., Mapping[str, AgentAdapter]] | None = None):
        self.printer = printer
        # 기본값을 정의 시점에 묶지 않는다(테스트에서 make_agents 를 바꿔 끼울 수 있게)
        self.agent_factory = agent_factory or make_agents
        self._console: IO[str] | None = None

    # ---------------------------------------------------------------- log
    def log(self, msg: str) -> None:
        line = f"[{dt.datetime.now():%H:%M:%S}] {msg}"
        self.printer(line)
        if self._console is not None:
            try:
                self._console.write(line + "\n")
                self._console.flush()
            except OSError:
                pass

    # ---------------------------------------------------------------- run
    def run(self, opts: RunOptions) -> RunOutcome:
        allow = (DESIGN_FILENAME,) if opts.skip_design else ()
        try:
            workdir = check_workdir(opts.workdir, force=opts.force, allow=allow)
        except WorkdirRefused as e:
            raise OrchestratorError(str(e)) from e
        if opts.design_only and opts.skip_design:
            raise OrchestratorError("--design-only 와 --skip-design 은 함께 쓸 수 없습니다.")
        workdir.mkdir(parents=True, exist_ok=True)

        cfg = self._load_config(workdir, opts.overrides)
        if opts.skip_design and not (workdir / DESIGN_FILENAME).is_file():
            raise OrchestratorError(f"--skip-design 인데 {workdir / DESIGN_FILENAME} 이 없습니다.")
        agents = self._make_agents(cfg, opts.mock)

        with self._locked(workdir, "run") as lock:
            register_quietly(workdir)
            run_dir = create_run_dir(workdir)
            lock.set_run(run_dir.name)
            state = RunState(run_id=run_dir.name, task=opts.task, config=self._snapshot(cfg, opts))
            if opts.skip_design:
                state.mark_done("debate")
            state.save(run_dir)
            with self._console_to(run_dir):
                self.log(f"실행 시작: {run_dir.name}  (기록: {run_dir})")
                design = "설계 생략(기존 DESIGN.md)" if opts.skip_design else \
                    f"종합: {cfg.synth_name} / 토론 {cfg.debate_rounds}라운드"
                build = "구현 생략(설계만)" if opts.design_only else \
                    f"구현: {cfg.implementer} / 리뷰: {cfg.reviewer} / 리뷰 최대 {cfg.max_review}회"
                self.log(f"{design} / {build}" + (" / mock" if opts.mock else ""))
                self.log("모델: " + " / ".join(
                    f"{n} {getattr(cfg, n).model or '기본'}" + (f"({getattr(cfg, n).effort})" if getattr(cfg, n).effort else "")
                    for n in ("claude", "codex")))
                return self._execute(workdir, run_dir, cfg, agents, state)

    # ---------------------------------------------------------------- resume
    def resume(self, workdir: Path, run_id: str | None = None,
               max_review: int | None = None) -> RunOutcome:
        workdir = Path(workdir).expanduser().resolve()
        run_dir = self._find_run(workdir, run_id)
        state = RunState.load(run_dir)
        prev_max = int(state.config.get("max_review") or 0)

        if state.status == DONE_UNAPPROVED:
            # 리뷰 상한을 다 쓴 실행: 상한을 늘려 주면 마지막 리뷰를 반영하는 라운드부터 이어간다
            if max_review is None or max_review <= prev_max:
                raise OrchestratorError(
                    f"마지막 실행({state.run_id})은 리뷰 {prev_max}회를 모두 써서 미승인으로 끝났습니다. "
                    f"이어가려면 상한을 늘리세요: duet resume --workdir {workdir} --max-review {prev_max + 1}"
                )
        elif state.finished:
            raise OrchestratorError(
                f"마지막 실행({state.run_id})은 이미 끝났습니다 (status={state.status}). "
                "새로 시작하려면 `duet run` 을 쓰세요."
            )

        overrides = {k: state.config.get(k) for k in CONFIG_KEYS}
        if max_review is not None:
            overrides["max_review"] = max_review
        cfg = self._load_config(workdir, overrides)
        mock = bool(state.config.get("mock"))
        agents = self._make_agents(cfg, mock)

        with self._locked(workdir, "resume") as lock:
            # 잠금을 잡은 뒤 다시 읽는다(그 사이 다른 프로세스가 바꿨을 수 있음)
            state = RunState.load(run_dir)
            lock.set_run(run_dir.name)
            register_quietly(workdir)
            state.config["max_review"] = cfg.max_review
            with self._console_to(run_dir):
                self.log(f"이어하기: {state.run_id}  (이전 status={state.status}, phase={state.phase}, "
                         f"step={state.step}, round={state.round})"
                         + (f" / 리뷰 상한 {prev_max} → {cfg.max_review}회" if cfg.max_review != prev_max else ""))
                state.status = RUNNING
                state.error = None
                state.save(run_dir)
                return self._execute(workdir, run_dir, cfg, agents, state)

    # ---------------------------------------------------------------- core
    def _execute(self, workdir: Path, run_dir: Path, cfg: Config,
                 agents: Mapping[str, AgentAdapter], state: RunState) -> RunOutcome:
        ctx = PhaseContext(task=state.task, workdir=workdir, cfg=cfg, agents=agents, state=state,
                           transcript=Transcript(run_dir), run_dir=run_dir, log=self.log)
        design_only = bool(state.config.get("design_only"))
        try:
            if not state.is_done("debate"):
                DebatePhase(ctx).run()
                state.mark_done("debate")
                state.save(run_dir)
            if design_only:
                state.status = DONE_DESIGN
                ctx.set_position(PHASE_DONE, "design_only", state.round)
                state.save(run_dir)
                self.log(f"설계만 완료. {workdir / DESIGN_FILENAME} 를 확인하세요.")
                return RunOutcome(state, run_dir)
            approved = BuildPhase(ctx).run()
        except PhaseStop as stop:
            self.log(f"중단: {stop}")
            if state.status == STOPPED_RATE_LIMIT:
                self.log(f"한도 도달. 나중에 `duet resume --workdir {workdir}` 으로 이어서 실행할 수 있습니다.")
            elif state.status == FAILED:
                self.log(f"실패 기록을 확인한 뒤 `duet resume --workdir {workdir}` 으로 다시 시도할 수 있습니다.")
            self.log(f"기록: {run_dir}")
            return RunOutcome(state, run_dir, stop)
        except GitError as e:
            state.status = FAILED
            state.error = f"git 오류: {e}"
            state.save(run_dir)
            self.log(f"중단: git 오류 — {e}")
            self.log("작업 폴더의 git 상태를 확인한 뒤(예: 에이전트가 만든 하위 저장소, 서명 설정) "
                     f"`duet resume --workdir {workdir}` 으로 이어서 실행할 수 있습니다.")
            return RunOutcome(state, run_dir)
        except KeyboardInterrupt:
            # Ctrl-C 또는 UI 의 중지(SIGTERM → KeyboardInterrupt). 진행 중이던 호출은 runner 가 이미 종료함.
            state.status = STOPPED_USER
            state.error = f"사용자 중단 ({state.phase}/{state.step} round {state.round})"
            state.save(run_dir)
            self.log(f"사용자 중단. `duet resume --workdir {workdir}` 으로 이어서 실행할 수 있습니다.")
            return RunOutcome(state, run_dir)
        except Exception as e:
            # 예상 못 한 오류도 상태는 남긴다(running 으로 남으면 UI/resume 가 헷갈림)
            state.status = FAILED
            state.error = f"내부 오류: {type(e).__name__}: {e}"
            state.save(run_dir)
            self.log(f"중단: 내부 오류 — {type(e).__name__}: {e}")
            raise

        if approved:
            self.log("✅ 리뷰 승인으로 종료")
        else:
            self.log(f"⚠️ {cfg.max_review}회 안에 승인되지 않음. 마지막 리뷰를 확인하세요: "
                     f"{run_dir / (state.last_review or '')}")
            self.log(f"계속하려면: duet resume --workdir {workdir} --max-review {min(cfg.max_review + 1, 10)}")
        self.log(f"전체 대화 기록: {run_dir}")
        return RunOutcome(state, run_dir)

    # ---------------------------------------------------------------- helpers
    def _locked(self, workdir: Path, verb: str) -> RunLock:
        lock = RunLock(workdir, command=f"duet {verb} " + " ".join(sys.argv[1:]))
        try:
            return lock.acquire()
        except LockBusy as e:
            raise OrchestratorError(str(e)) from e

    def _console_to(self, run_dir: Path) -> "_ConsoleScope":
        return _ConsoleScope(self, run_dir / CONSOLE_LOG)

    def _load_config(self, workdir: Path, overrides: Mapping[str, Any]) -> Config:
        try:
            return load_config(workdir, overrides)
        except ConfigError as e:
            raise OrchestratorError(f"설정 오류: {e}") from e

    def _make_agents(self, cfg: Config, mock: bool) -> Mapping[str, AgentAdapter]:
        agents = self.agent_factory(cfg, mock=mock)
        for name in (cfg.implementer, cfg.reviewer, cfg.synth_name):
            try:
                agents[name].check()
            except AgentNotAvailable as e:
                raise OrchestratorError(str(e)) from e
        return agents

    @staticmethod
    def _snapshot(cfg: Config, opts: RunOptions) -> dict[str, Any]:
        return {
            "implementer": cfg.implementer, "reviewer": cfg.reviewer, "synth": cfg.synth_name,
            "debate_rounds": cfg.debate_rounds, "max_review": cfg.max_review,
            "claude.model": cfg.claude.model, "claude.effort": cfg.claude.effort,
            "codex.model": cfg.codex.model, "codex.effort": cfg.codex.effort,
            "design_only": opts.design_only, "skip_design": opts.skip_design, "mock": opts.mock,
        }

    @staticmethod
    def _find_run(workdir: Path, run_id: str | None) -> Path:
        if run_id:
            candidates = [p for p in list_run_dirs(workdir) if p.name == run_id]
            if not candidates:
                raise OrchestratorError(f"실행 기록을 찾을 수 없습니다: {run_id}")
            return candidates[0]
        run_dir = latest_run_dir(workdir)
        if run_dir is None:
            raise OrchestratorError(f"{workdir} 에 이어할 실행 기록이 없습니다 (.duet/runs 비어 있음).")
        return run_dir


class _ConsoleScope:
    """with 블록 동안 Orchestrator.log 를 console.log 에도 쓴다."""

    def __init__(self, orch: Orchestrator, path: Path):
        self.orch, self.path = orch, path

    def __enter__(self) -> None:
        self.orch._console = self.path.open("a", encoding="utf-8")

    def __exit__(self, *exc: object) -> None:
        if self.orch._console is not None:
            self.orch._console.close()
        self.orch._console = None
