"""Orchestrator — 단계 진행과 resume.

check() 두 어댑터
DebatePhase (skip-design 아니면) → design-only 면 종료
BuildPhase
각 스텝 직후 RunState 저장. resume 은 마지막 run 의 완료 스텝 다음부터 이어간다.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from duet.agents import AgentAdapter, AgentNotAvailable, make_agents
from duet.config import Config, ConfigError, load_config
from duet.phases.build import BuildPhase
from duet.phases.common import PhaseContext, PhaseStop
from duet.phases.debate import DESIGN_FILENAME, DebatePhase
from duet.state import (
    DONE_APPROVED,
    DONE_DESIGN,
    DONE_UNAPPROVED,
    FAILED,
    PHASE_DONE,
    RUNNING,
    STOPPED_RATE_LIMIT,
    RunState,
    create_run_dir,
    latest_run_dir,
    list_run_dirs,
)
from duet.transcript import Transcript
from duet.workspace import WorkdirRefused, check_workdir

Logger = Callable[[str], None]

CONFIG_KEYS = ("implementer", "reviewer", "synth", "debate_rounds", "max_review")
RUN_FLAG_KEYS = ("design_only", "skip_design", "mock")


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
            return 0
        if s == DONE_UNAPPROVED:
            return 1
        return 3


def default_logger(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


class Orchestrator:
    def __init__(self, log: Logger = default_logger,
                 agent_factory: Callable[..., Mapping[str, AgentAdapter]] | None = None):
        self.log = log
        # 기본값을 정의 시점에 묶지 않는다(테스트에서 make_agents 를 바꿔 끼울 수 있게)
        self.agent_factory = agent_factory or make_agents

    # ---------------------------------------------------------------- run
    def run(self, opts: RunOptions) -> RunOutcome:
        try:
            workdir = check_workdir(opts.workdir, force=opts.force)
        except WorkdirRefused as e:
            raise OrchestratorError(str(e)) from e
        workdir.mkdir(parents=True, exist_ok=True)

        cfg = self._load_config(workdir, opts.overrides)
        if opts.skip_design and not (workdir / DESIGN_FILENAME).is_file():
            raise OrchestratorError(f"--skip-design 인데 {workdir / DESIGN_FILENAME} 이 없습니다.")
        if opts.design_only and opts.skip_design:
            raise OrchestratorError("--design-only 와 --skip-design 은 함께 쓸 수 없습니다.")
        agents = self._make_agents(cfg, opts.mock)

        run_dir = create_run_dir(workdir)
        state = RunState(run_id=run_dir.name, task=opts.task, config=self._snapshot(cfg, opts))
        if opts.skip_design:
            state.mark_done("debate")
        state.save(run_dir)
        self.log(f"실행 시작: {run_dir.name}  (기록: {run_dir})")
        self.log(f"구현: {cfg.implementer} / 리뷰: {cfg.reviewer} / 종합: {cfg.synth_name} / "
                 f"토론 {cfg.debate_rounds}라운드 / 리뷰 최대 {cfg.max_review}회"
                 + (" / mock" if opts.mock else ""))
        return self._execute(workdir, run_dir, cfg, agents, state)

    # ---------------------------------------------------------------- resume
    def resume(self, workdir: Path, run_id: str | None = None) -> RunOutcome:
        workdir = Path(workdir).expanduser().resolve()
        run_dir = self._find_run(workdir, run_id)
        state = RunState.load(run_dir)
        if state.finished:
            raise OrchestratorError(
                f"마지막 실행({state.run_id})은 이미 끝났습니다 (status={state.status}). "
                "새로 시작하려면 `duet run` 을 쓰세요."
            )
        overrides = {k: state.config.get(k) for k in CONFIG_KEYS}
        cfg = self._load_config(workdir, overrides)
        mock = bool(state.config.get("mock"))
        agents = self._make_agents(cfg, mock)

        self.log(f"이어하기: {state.run_id}  (이전 status={state.status}, phase={state.phase}, "
                 f"step={state.step}, round={state.round})")
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
                self.log("한도 도달. 나중에 `duet resume --workdir ...` 으로 이어서 실행할 수 있습니다.")
            elif state.status == FAILED:
                self.log("실패 기록을 확인한 뒤 `duet resume --workdir ...` 으로 다시 시도할 수 있습니다.")
            self.log(f"기록: {run_dir}")
            return RunOutcome(state, run_dir, stop)

        if approved:
            self.log("✅ 리뷰 승인으로 종료")
        else:
            self.log(f"⚠️ {cfg.max_review}회 안에 승인되지 않음. 마지막 리뷰를 확인하세요: "
                     f"{run_dir / (state.last_review or '')}")
        self.log(f"전체 대화 기록: {run_dir}")
        return RunOutcome(state, run_dir)

    # ---------------------------------------------------------------- helpers
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
