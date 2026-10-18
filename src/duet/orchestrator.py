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
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import IO, Any, Callable, Mapping

from duet.agents import (AgentAdapter, AgentNotAvailable, ClaudeCodeAdapter, CodexAdapter, MockAdapter,
                         make_agents, make_role_agents)
from duet.config import (
    Config, ConfigError, dedup_agent_config, describe_effort, describe_model, load_config, report_agent_config,
)
from duet.dedup import DEDUP_ROLE
from duet.lock import LockBusy, RunLock
from duet.phases.build import BuildPhase
from duet.phases.common import PhaseContext, PhaseStop
from duet.phases.debate import DESIGN_FILENAME, DebatePhase
from duet.phases.extra import run_audit, run_explore
from duet.report import REPORT_ROLE, run_report
from duet.registry import register_quietly
from duet.runner import env_drops
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
from duet import attachments
from duet.transcript import Transcript
from duet.workflow import SOURCE_LABELS, Workflow, WorkflowError, classic, load_workflow
from duet.workspace import GitError, WorkdirRefused, check_workdir

Printer = Callable[[str], None]

CONFIG_KEYS = ("workflow", "implementer", "reviewer", "synth", "debate_rounds", "max_review",
               "claude.model", "claude.effort", "codex.model", "codex.effort",
               "claude.step_effort", "codex.step_effort", "claude.step_model", "codex.step_model", "step_overrides",
               "test_command", "block_severity", "stall_rounds", "require_tests_pass",
               "review_diff", "repro_tests", "review_packet", "review_json", "review_session",
               "review_session_rounds", "review_gates", "arbiter", "test_guard", "claude_sandbox", "spec_gate",
               "wait_on_limit", "limit_wait_max_min", "dedup", "dedup_agent", "dedup_model", "dedup_effort",
               "report", "report_agent", "report_model", "report_effort",
               "access", "web_search", "package_lookup", "browser_check",
               "timeout_sec", "test_timeout_sec", "max_diff_chars")
CONSOLE_LOG = "console.log"
CHANGES_DIR = "docs/changes"   # 기존 프로젝트의 변경 설계를 두는 곳 (DESIGN.md 19.5)

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
    register: bool = True     # UI 프로젝트 목록에 등록 (벤치마크 실행은 안 함, DESIGN.md 28.2)
    attachments: list[Path] = field(default_factory=list)     # 과제 첨부 (DESIGN.md 33.3)


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
                 agent_factory: Callable[..., Mapping[str, AgentAdapter]] | None = None,
                 role_factory: Callable[..., Mapping[str, AgentAdapter]] | None = None):
        self.printer = printer
        # 기본값을 정의 시점에 묶지 않는다(테스트에서 make_agents 를 바꿔 끼울 수 있게)
        self.agent_factory = agent_factory or make_agents
        # classic 이 아닌 워크플로: 역할 이름 → 어댑터 (DESIGN.md 19장)
        self.role_factory = role_factory or make_role_agents
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
        try:
            attach = attachments.check(opts.attachments)
        except attachments.AttachmentError as e:
            raise OrchestratorError(str(e)) from e
        workdir.mkdir(parents=True, exist_ok=True)

        cfg = self._load_config(workdir, opts.overrides)
        wf, cfg = self._resolve_workflow(workdir, cfg, opts)
        if opts.skip_design and not (workdir / DESIGN_FILENAME).is_file():
            raise OrchestratorError(f"--skip-design 인데 {workdir / DESIGN_FILENAME} 이 없습니다.")
        if opts.design_only and wf.first("debate") is None:
            raise OrchestratorError(f"워크플로 {wf.name} 에는 설계(debate) 단계가 없어 --design-only 를 쓸 수 없습니다.")
        if wf.first("build") and not wf.first("debate") and not (workdir / DESIGN_FILENAME).is_file():
            raise OrchestratorError(f"워크플로 {wf.name} 에는 설계 단계가 없어 {workdir / DESIGN_FILENAME} 이 필요합니다.")
        agents = self._make_agents(cfg, opts.mock, wf)

        with self._locked(workdir, "run") as lock:
            if opts.register:
                register_quietly(workdir)
            run_dir = create_run_dir(workdir)
            lock.set_run(run_dir.name)
            state = RunState(run_id=run_dir.name, task=opts.task, config=self._snapshot(cfg, opts),
                             workflow=None if wf.is_classic else wf.to_dict())
            state.attachments = attachments.copy_into(run_dir, attach)
            debate = wf.first("debate")
            if debate is not None and debate.output == "change" and not opts.skip_design:
                state.design_doc = f"{CHANGES_DIR}/{run_dir.name}.md"   # DESIGN.md 19.5
            if opts.skip_design:
                state.mark_done("debate")
            state.save(run_dir)
            with self._console_to(run_dir):
                self.log(f"실행 시작: {run_dir.name}  (기록: {run_dir})")
                self.log(f"권한: {cfg.access} · 웹 검색 {cfg.web_search} · 브라우저 확인 {cfg.browser_check}"
                         + (f" · 첨부 {len(state.attachments)}개" if state.attachments else ""))
                if wf.is_classic:
                    design = "설계 생략(기존 DESIGN.md)" if opts.skip_design else \
                        f"종합: {cfg.synth_name} / 토론 {cfg.debate_rounds}라운드"
                    build = "구현 생략(설계만)" if opts.design_only else \
                        f"구현: {cfg.implementer} / 리뷰: {cfg.reviewer} / 리뷰 최대 {cfg.max_review}회"
                    self.log(f"{design} / {build}" + (" / mock" if opts.mock else ""))
                    self.log("모델: " + " / ".join(
                        f"{n} {describe_model(wf.roles[n].agent_config(cfg))}"
                        + (f"({describe_effort(wf.roles[n].agent_config(cfg))})" if describe_effort(wf.roles[n].agent_config(cfg)) else "")
                        for n in ("claude", "codex")))
                else:
                    flags = [x for x, on in (("설계 생략", opts.skip_design), ("설계만", opts.design_only),
                                             ("mock", opts.mock)) if on]
                    self.log(f"워크플로: {wf.name} ({SOURCE_LABELS.get(wf.source, wf.source)}) — {wf.summary()}"
                             + (f" / {', '.join(flags)}" if flags else ""))
                    self.log(f"토론 {cfg.debate_rounds}라운드 / 리뷰 최대 {cfg.max_review}회")
                    self.log("역할: " + " / ".join(self._describe_role(wf, n, cfg) for n in wf.used_roles()))
                self._log_env_drops(cfg, opts.mock)
                return self._execute(workdir, run_dir, cfg, agents, state, wf)

    # ---------------------------------------------------------------- resume
    def resume(self, workdir: Path, run_id: str | None = None,
               max_review: int | None = None) -> RunOutcome:
        workdir = Path(workdir).expanduser().resolve()
        run_dir = self._find_run(workdir, run_id)
        state = RunState.load(run_dir)
        prev_max = int(state.config.get("max_review") or 0)

        stalled_early = (state.status == DONE_UNAPPROVED and state.stop_reason in ("stalled", "arbiter_final")
                         and state.round < prev_max)
        if state.status == DONE_UNAPPROVED and not stalled_early:
            # 리뷰 상한을 다 쓴 실행: 상한을 늘려 주면 마지막 리뷰를 반영하는 라운드부터 이어간다
            if max_review is None or max_review <= prev_max:
                raise OrchestratorError(
                    f"마지막 실행({state.run_id})은 리뷰 {prev_max}회를 모두 써서 미승인으로 끝났습니다. "
                    f"이어가려면 상한을 늘리세요: duet resume --workdir {workdir} --max-review {prev_max + 1}"
                )
        elif state.finished and not stalled_early:
            raise OrchestratorError(
                f"마지막 실행({state.run_id})은 이미 끝났습니다 (status={state.status}). "
                "새로 시작하려면 `duet run` 을 쓰세요."
            )

        overrides = {k: state.config.get(k) for k in CONFIG_KEYS}
        if max_review is not None:
            overrides["max_review"] = max_review
        cfg = self._load_config(workdir, overrides)
        mock = bool(state.config.get("mock"))
        try:
            wf = Workflow.from_dict(state.workflow) if state.workflow else classic(cfg)
        except WorkflowError as e:
            raise OrchestratorError(f"저장된 워크플로를 읽을 수 없습니다: {e}") from e
        agents = self._make_agents(cfg, mock, wf)

        with self._locked(workdir, "resume") as lock:
            # 잠금을 잡은 뒤 다시 읽는다(그 사이 다른 프로세스가 바꿨을 수 있음)
            state = RunState.load(run_dir)
            lock.set_run(run_dir.name)
            register_quietly(workdir)
            state.config["max_review"] = cfg.max_review
            if state.status == DONE_UNAPPROVED and "build" in state.done:
                state.done.remove("build")   # 리뷰 루프를 이어간다
                if "report" in state.done:   # 끝나면 결과 요약을 다시 만든다 (DESIGN.md 32.1)
                    state.done.remove("report")
                state.report = None
            if state.stop_reason in ("stalled", "arbiter_final"):
                # 사람이 계속하라고 했으니 수렴 판단은 지금부터 다시 센다
                state.stall_baseline_round = state.round
                state.stop_reason = None
            with self._console_to(run_dir):
                self.log(f"이어하기: {state.run_id}  (이전 status={state.status}, phase={state.phase}, "
                         f"step={state.step}, round={state.round})"
                         + (f" / 리뷰 상한 {prev_max} → {cfg.max_review}회" if cfg.max_review != prev_max else ""))
                self._log_env_drops(cfg, mock)
                state.status = RUNNING
                state.error = None
                state.save(run_dir)
                return self._execute(workdir, run_dir, cfg, agents, state, wf)

    # ---------------------------------------------------------------- core
    def _execute(self, workdir: Path, run_dir: Path, cfg: Config,
                 agents: Mapping[str, AgentAdapter], state: RunState,
                 wf: Workflow | None = None) -> RunOutcome:
        wf = wf or classic(cfg)
        ctx = PhaseContext(task=state.task, workdir=workdir, cfg=cfg, agents=agents, state=state,
                           transcript=Transcript(run_dir), run_dir=run_dir, log=self.log,
                           workflow=None if wf.is_classic else wf)
        design_only = bool(state.config.get("design_only"))
        approved: bool | None = None
        try:
            for step in wf.steps:
                if step.kind == "explore":
                    run_explore(ctx, step)
                elif step.kind == "debate":
                    if not state.is_done("debate"):
                        DebatePhase(ctx, step).run()
                        state.mark_done("debate")
                        state.save(run_dir)
                    if design_only:
                        return self._design_done(ctx, workdir, run_dir, "design_only")
                elif step.kind == "build":
                    if not state.is_done("build"):
                        approved = BuildPhase(ctx, step=step).run()
                        state.mark_done("build")
                        state.save(run_dir)
                    else:
                        approved = bool(state.review_history and state.review_history[-1].get("approved"))
                elif step.kind == "audit":
                    if approved:
                        run_audit(ctx, step)
                    elif not state.is_done(f"audit:{step.id}"):
                        self.log(f"감사 건너뜀({step.id}): 승인되지 않아 감사하지 않습니다.")
                        state.mark_done(f"audit:{step.id}")
                        state.save(run_dir)
            if approved is None:
                return self._design_done(ctx, workdir, run_dir, "no_build")
            if approved:
                # 감사 단계가 위치를 바꿨을 수 있다. 감사는 참고용이라 승인 상태를 유지한다.
                state.status = DONE_APPROVED
                ctx.set_position(PHASE_DONE, "approved", state.round)
                state.save(run_dir)
            if state.status in (DONE_APPROVED, DONE_UNAPPROVED):
                self._report(ctx, run_dir)          # 결과 요약 (DESIGN.md 32장, 보조 호출)
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

        if approved and state.stop_reason == "arbiter":
            self.log("✅ 중재로 승인 (중재 결과: " + run_dir.joinpath((state.arbiter or {}).get("file") or "").name + ")")
        elif approved:
            self.log("✅ 리뷰 승인으로 종료")
        elif state.stop_reason in ("arbiter_upheld", "arbiter_final"):
            self.log("⚠️ 중재 뒤에도 막는 지적이 남아 멈춥니다: " + ", ".join((state.arbiter or {}).get("upheld") or [])
                     + f". 중재 결과와 마지막 리뷰를 보고 직접 판단하세요: {run_dir}")
        elif state.stop_reason == "stalled":
            self.log(f"계속하려면: duet resume --workdir {workdir}"
                     + (f" --max-review {min(cfg.max_review + 1, 10)}" if state.round >= cfg.max_review else ""))
        else:
            self.log(f"⚠️ {cfg.max_review}회 안에 승인되지 않음. 마지막 리뷰를 확인하세요: "
                     f"{run_dir / (state.last_review or '')}")
            self.log(f"계속하려면: duet resume --workdir {workdir} --max-review {min(cfg.max_review + 1, 10)}")
        self.log(f"전체 대화 기록: {run_dir}")
        return RunOutcome(state, run_dir)

    def _design_done(self, ctx: PhaseContext, workdir: Path, run_dir: Path, why: str) -> RunOutcome:
        state = ctx.state
        state.status = DONE_DESIGN
        ctx.set_position(PHASE_DONE, "design_only", state.round)
        state.save(run_dir)
        doc = workdir / (state.design_doc or DESIGN_FILENAME)
        if state.is_done("debate") and doc.is_file():
            self.log(f"설계만 완료. {doc} 를 확인하세요.")
        else:
            self.log(f"구현 단계가 없는 워크플로라 여기서 끝납니다. 기록: {run_dir}")
        return RunOutcome(state, run_dir)

    # ---------------------------------------------------------------- workflow
    def _resolve_workflow(self, workdir: Path, cfg: Config, opts: RunOptions) -> tuple[Workflow, Config]:
        """고른 워크플로를 읽고, 템플릿의 rounds·max_review 를 설정에 반영한다 (CLI 인자가 우선)."""
        try:
            wf = load_workflow(cfg.workflow, workdir, cfg)
        except WorkflowError as e:
            raise OrchestratorError(f"워크플로 오류: {e}") from e
        unknown = sorted(set(cfg.step_overrides) - set(wf.roles))
        if unknown:
            raise OrchestratorError(f"설정 오류: 칸 단위 지정(step_overrides)의 역할 {', '.join(unknown)} 이 "
                                    f"워크플로 {wf.name} 에 없습니다 (가능: {', '.join(wf.roles)})")
        if wf.is_classic:
            return wf, cfg
        given = [f"--{k}" for k in ("implementer", "reviewer", "synth") if opts.overrides.get(k)]
        if given:
            raise OrchestratorError(f"{', '.join(given)} 는 classic 워크플로에서만 쓸 수 있습니다 "
                                    f"(워크플로 {wf.name} 은 역할을 템플릿에서 정합니다).")
        changes: dict[str, Any] = {}
        debate = wf.first("debate")
        if debate is not None:
            if len(debate.proposers) == 1:
                changes["debate_rounds"] = 0
            elif opts.overrides.get("debate_rounds") is None and debate.rounds is not None:
                changes["debate_rounds"] = debate.rounds
        build = wf.first("build")
        if build is not None and opts.overrides.get("max_review") is None and build.max_review is not None:
            changes["max_review"] = build.max_review
        cfg = replace(cfg, **changes)
        try:
            cfg.validate()
        except ConfigError as e:
            raise OrchestratorError(f"설정 오류: {e}") from e
        return wf, cfg

    @staticmethod
    def _describe_role(wf: Workflow, name: str, cfg: Config) -> str:
        role = wf.roles[name]
        ac = role.agent_config(cfg)
        effort = describe_effort(ac)
        return f"{name}={role.agent}({describe_model(ac)}" + (f", 강도 {effort}" if effort else "") + ")"

    # ---------------------------------------------------------------- helpers
    def _locked(self, workdir: Path, verb: str) -> RunLock:
        lock = RunLock(workdir, command=" ".join(["duet", *sys.argv[1:]]) if sys.argv[1:] else f"duet {verb}")
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

    def _make_agents(self, cfg: Config, mock: bool, wf: Workflow | None = None) -> Mapping[str, AgentAdapter]:
        if wf is not None and not wf.is_classic:
            agents = self.role_factory(cfg, wf, mock=mock)
            names = wf.used_roles()
        else:
            agents = self.agent_factory(cfg, mock=mock)
            names = [cfg.implementer, cfg.reviewer, cfg.synth_name]
        for name in dict.fromkeys(names):
            try:
                agents[name].check()
            except AgentNotAvailable as e:
                raise OrchestratorError(str(e)) from e
        return self._add_report(cfg, mock, self._add_dedup(cfg, mock, agents))

    def _add_report(self, cfg: Config, mock: bool, agents: Mapping[str, AgentAdapter]) -> Mapping[str, AgentAdapter]:
        """결과 요약자 (DESIGN.md 32.2). 쓸 수 없으면 건너뛴다(보조 호출)."""
        if not cfg.report or REPORT_ROLE in agents:
            return agents
        out = dict(agents)
        if mock:
            out[REPORT_ROLE] = MockAdapter(label=REPORT_ROLE)
            return out
        ac = report_agent_config(cfg)
        adapter = ClaudeCodeAdapter(cfg, ac) if cfg.report_agent == "claude" else CodexAdapter(cfg, ac)
        try:
            adapter.check()
        except AgentNotAvailable:
            self.log(f"결과 요약자({cfg.report_agent})를 쓸 수 없어 건너뜁니다.")
            return agents
        out[REPORT_ROLE] = adapter
        return out

    def _report(self, ctx: PhaseContext, run_dir: Path, *, force: bool = False) -> None:
        """보조 호출: 한도에 걸려도 실행 결과(승인·미승인)와 위치는 그대로 둔다."""
        st = ctx.state
        keep = (st.status, st.stop_reason, st.error, st.phase, st.step, st.round)
        try:
            run_report(ctx, force=force)
        except PhaseStop as e:
            st.status, st.stop_reason, st.error, st.phase, st.step, st.round = keep
            st.mark_done("report")
            st.save(run_dir)
            self.log(f"결과 요약을 건너뜀: {e}. 나중에 `duet report --workdir {ctx.workdir}` 로 만들 수 있습니다.")
            return
        st.status, st.stop_reason, st.error, st.phase, st.step, st.round = keep
        st.save(run_dir)

    def report(self, workdir: Path, run_id: str | None = None, *, mock: bool | None = None) -> Path | None:
        """끝난 실행의 결과 요약을 (다시) 만든다: `duet report` (DESIGN.md 32.3)."""
        workdir = Path(workdir).expanduser().resolve()
        run_dir = self._find_run(workdir, run_id)
        state = RunState.load(run_dir)
        if state.status not in (DONE_APPROVED, DONE_UNAPPROVED):
            raise OrchestratorError(f"승인·미승인으로 끝난 실행만 요약할 수 있습니다 ({state.run_id}: status={state.status}).")
        cfg = replace(self._load_config(workdir, {k: state.config.get(k) for k in CONFIG_KEYS}), report=True)
        use_mock = bool(state.config.get("mock")) if mock is None else mock
        agents = self._add_report(cfg, use_mock, {})
        if REPORT_ROLE not in agents:
            raise OrchestratorError(f"결과 요약에 쓸 CLI({cfg.report_agent})를 찾을 수 없습니다.")
        with self._locked(workdir, "report") as lock:
            state = RunState.load(run_dir)
            lock.set_run(run_dir.name)
            ctx = PhaseContext(task=state.task, workdir=workdir, cfg=cfg, agents=agents, state=state,
                               transcript=Transcript(run_dir), run_dir=run_dir, log=self.log, workflow=None)
            with self._console_to(run_dir):
                self._report(ctx, run_dir, force=True)
        return run_dir / state.report if state.report else None

    def _add_dedup(self, cfg: Config, mock: bool, agents: Mapping[str, AgentAdapter]) -> Mapping[str, AgentAdapter]:
        """재제기 확인자(DESIGN.md 26.2). 워크플로에 dedup 역할이 있으면 그것, 없으면 설정의 작은 모델."""
        if not cfg.dedup or DEDUP_ROLE in agents:
            return agents
        out = dict(agents)
        if mock:
            out[DEDUP_ROLE] = MockAdapter(label=DEDUP_ROLE)
            return out
        ac = dedup_agent_config(cfg)
        adapter = ClaudeCodeAdapter(cfg, ac) if cfg.dedup_agent == "claude" else CodexAdapter(cfg, ac)
        try:
            adapter.check()
        except AgentNotAvailable:
            self.log(f"재제기 확인자({cfg.dedup_agent})를 쓸 수 없어 건너뜁니다.")
            return agents
        out[DEDUP_ROLE] = adapter
        return out

    def _log_env_drops(self, cfg: Config, mock: bool) -> None:
        dropped = [] if mock else env_drops(cfg.env_strip, cfg.env_keep)
        if dropped:  # 이름만 남긴다(값은 남기지 않음)
            self.log("에이전트·테스트에 넘기지 않는 환경 변수: " + ", ".join(dropped))

    @staticmethod
    def _snapshot(cfg: Config, opts: RunOptions) -> dict[str, Any]:
        return {
            "implementer": cfg.implementer, "reviewer": cfg.reviewer, "synth": cfg.synth_name,
            "debate_rounds": cfg.debate_rounds, "max_review": cfg.max_review,
            "claude.model": cfg.claude.model, "claude.effort": cfg.claude.effort,
            "codex.model": cfg.codex.model, "codex.effort": cfg.codex.effort,
            "claude.step_effort": dict(cfg.claude.step_effort), "codex.step_effort": dict(cfg.codex.step_effort),
            "claude.step_model": dict(cfg.claude.step_model), "codex.step_model": dict(cfg.codex.step_model),
            "step_overrides": {r: {s: dict(v) for s, v in steps.items()} for r, steps in cfg.step_overrides.items()},
            "workflow": cfg.workflow,
            "test_command": cfg.test_command, "block_severity": cfg.block_severity,
            "stall_rounds": cfg.stall_rounds, "require_tests_pass": cfg.require_tests_pass,
            "review_diff": cfg.review_diff, "repro_tests": cfg.repro_tests,
            "review_packet": cfg.review_packet, "review_json": cfg.review_json,
            "review_session": cfg.review_session, "review_session_rounds": cfg.review_session_rounds,
            "review_gates": cfg.review_gates, "arbiter": cfg.arbiter,
            "test_guard": cfg.test_guard, "claude_sandbox": cfg.claude_sandbox, "spec_gate": cfg.spec_gate,
            "wait_on_limit": cfg.wait_on_limit, "limit_wait_max_min": cfg.limit_wait_max_min,
            "access": cfg.access, "web_search": cfg.web_search, "package_lookup": cfg.package_lookup,
            "browser_check": cfg.browser_check,
            "report": cfg.report, "report_agent": cfg.report_agent, "report_model": cfg.report_model,
            "report_effort": cfg.report_effort,
            "dedup": cfg.dedup, "dedup_agent": cfg.dedup_agent, "dedup_model": cfg.dedup_model,
            "dedup_effort": cfg.dedup_effort,
            "timeout_sec": cfg.timeout_sec, "test_timeout_sec": cfg.test_timeout_sec,
            "max_diff_chars": cfg.max_diff_chars,
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
