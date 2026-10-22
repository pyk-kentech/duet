"""tenure 명령줄 진입점. 서브커맨드: run / resume / log"""

from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path
from typing import Sequence

from tenure import __version__
from tenure.config import ConfigError, parse_set_step, parse_step_effort, parse_step_model
from tenure.orchestrator import Orchestrator, OrchestratorError, RunOptions
from tenure.state import RunState
from tenure.worktree import all_run_dirs
from tenure.transcript import Transcript

EXIT_OK = 0
EXIT_UNAPPROVED = 1
EXIT_USAGE = 2
EXIT_STOPPED = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tenure",
        description="Claude Code와 Codex CLI가 설계를 토론하고 서로의 코드를 교차 리뷰하는 도구",
    )
    parser.add_argument("--version", action="version", version=f"tenure {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    p_run = sub.add_parser("run", help="설계 토론 → 구현 → 교차 리뷰를 처음부터 실행")
    p_run.add_argument("task", help="만들 것 (한 줄 설명, 또는 @파일경로로 긴 설명)")
    _add_workdir(p_run)
    p_run.add_argument("--mock", action="store_true", help="실제 CLI 호출 없이 흐름만 테스트")
    p_run.add_argument("--workflow", metavar="NAME|@FILE",
                       help="워크플로 (기본: auto = 자동 선택). 목록: tenure workflows")
    p_run.add_argument("--implementer", choices=["claude", "codex"], help="구현 담당 (기본: claude, classic 전용)")
    p_run.add_argument("--reviewer", choices=["claude", "codex"], help="리뷰 담당 (기본: codex)")
    p_run.add_argument("--synth", choices=["claude", "codex"], help="최종 설계 종합 담당 (기본: 리뷰어)")
    p_run.add_argument("--debate-rounds", type=int, help="설계 토론 비판 라운드 수 (기본: 1, 최대 5)")
    p_run.add_argument("--max-review", type=int, help="구현-리뷰 최대 반복 (기본: 3, 최대 10)")
    p_run.add_argument("--design-only", action="store_true", help="설계 토론만 하고 종료")
    p_run.add_argument("--skip-design", action="store_true", help="기존 DESIGN.md로 바로 구현")
    p_run.add_argument("--force", action="store_true", help="커밋 안 된 변경이 있어도 진행")
    p_run.add_argument("--test-command", metavar="CMD",
                       help='구현 후 tenure 가 돌릴 테스트 명령 (기본: auto = tenure.toml → 자동 감지, "none" 이면 끔)')
    p_run.add_argument("--block-severity", choices=["P1", "P2", "P3"],
                       help="이 심각도 이상의 지적이 남아 있으면 반려 (기본: P2 → P3 만 남으면 승인)")
    p_run.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                       help="설정 덮어쓰기 (예: --set arbiter=false --set limit_wait_max_min=120). `tenure ui` 의 고급 설정과 같은 키")
    p_run.add_argument("--wait-on-limit", action="store_true",
                       help="구독 한도에 걸리면 재개 시각까지 기다렸다가 이어서 실행 (최대 limit_wait_max_min 분)")
    p_run.add_argument("--claude-sandbox", action="store_true",
                       help="Claude 구현자의 명령을 OS 샌드박스 안에서 실행 (Linux: bubblewrap·socat 필요)")
    p_run.add_argument("--no-arbiter", action="store_true",
                       help="수렴하지 않을 때 분쟁 중재자를 부르지 않고 바로 멈춤 (기본: 한 번 부름)")
    p_run.add_argument("--stall-rounds", type=int, metavar="N",
                       help="막는 지적 수가 N 라운드 연속 줄지 않으면 멈춤 (기본: 2, 0=끔)")
    for agent, example in (("claude", "opus, sonnet, claude-opus-5-5"), ("codex", "gpt-6.1-sol")):
        p_run.add_argument(f"--{agent}-model", metavar="MODEL", help=f"{agent} 모델 (예: {example}). 기본: CLI 기본값")
        p_run.add_argument(f"--{agent}-effort", metavar="LEVEL",
                           help=f"{agent} 추론 강도, 모든 단계에 적용 (예: low, medium, high, xhigh)")
        p_run.add_argument(f"--{agent}-step-effort", metavar="STEP=LEVEL,...",
                           help=f"{agent} 단계별 추론 강도 (예: review=high,fix=low). "
                                "단계: propose, critique, synthesize, implement, fix, review, rereview(2라운드부터 리뷰)"),
        p_run.add_argument(f"--{agent}-step-model", metavar="STEP=MODEL,...",
                           help=f"{agent} 단계별 모델 (예: implement={example.split(', ')[-1]}). 단계는 --{agent}-step-effort 와 같음")
    p_run.add_argument("--attach", action="append", default=None, metavar="FILE",
                       help="과제와 함께 줄 파일(여러 번): 화면 시안·참고 문서·스크린샷. 최대 10개·합 20MB")
    p_run.add_argument("--set-step", action="append", default=None, metavar="ROLE.STEP.KEY=VALUE",
                       help="칸(역할·단계) 하나의 모델·강도 (여러 번). 예: worker.part.model=claude-haiku-5-5, codex.review.effort=xhigh")
    p_run.add_argument("--run-id", metavar="ID", help="실행 id 를 미리 정함 (화면이 쓴다. 기본: 시각)")
    p_run.set_defaults(func=cmd_run)

    p_resume = sub.add_parser("resume", help="중단된 마지막 실행을 이어서 진행")
    _add_workdir(p_resume)
    p_resume.add_argument("--run", metavar="RUN_ID", help="특정 실행 ID (기본: 마지막 실행)")
    p_resume.add_argument("--max-review", type=int,
                          help="구현-리뷰 상한을 늘려서 이어감 (미승인으로 끝난 실행을 계속할 때 필요, 최대 10)")
    p_resume.set_defaults(func=cmd_resume)

    p_report = sub.add_parser("report", help="끝난 실행의 결과 요약 만들기 (작은 모델 1회, DESIGN.md 32장)")
    _add_workdir(p_report)
    p_report.add_argument("--run", metavar="RUN_ID", help="특정 실행 ID (기본: 마지막 실행)")
    p_report.add_argument("--mock", action="store_true", help="실제 CLI 호출 없이 (기본: 그 실행이 mock 이었는지 따름)")
    p_report.set_defaults(func=cmd_report)

    p_log = sub.add_parser("log", help="지난 실행 기록 보기")
    _add_workdir(p_log)
    p_log.add_argument("--full", action="store_true", help="전체 발언을 순서대로 출력")
    p_log.add_argument("--run", metavar="RUN_ID", help="특정 실행 ID (기본: 마지막 실행)")
    p_log.add_argument("--all", action="store_true", help="모든 실행을 한 줄씩 나열")
    p_log.set_defaults(func=cmd_log)

    # worktree 실행의 병합 (DESIGN.md 36.14)
    p_merge = sub.add_parser("merge", help="worktree 실행을 기준 브랜치로 병합 (먼저 점검, 막는 항목이 있으면 안 함)")
    _add_workdir(p_merge)
    p_merge.add_argument("--run", metavar="RUN_ID", required=True, help="병합할 실행 ID")
    p_merge.add_argument("--mode", choices=["squash", "merge"], default="squash", help="squash(기본, 한 커밋) 또는 merge(--no-ff)")
    p_merge.add_argument("--check", action="store_true", help="병합하지 않고 점검 결과만 보기")
    p_merge.set_defaults(func=cmd_merge)
    p_discard = sub.add_parser("discard", help="worktree 실행을 버림 (변경은 .tenure/discarded/ 에 패치로 남고 브랜치는 남음)")
    _add_workdir(p_discard)
    p_discard.add_argument("--run", metavar="RUN_ID", required=True, help="버릴 실행 ID")
    p_discard.set_defaults(func=cmd_discard)
    p_pick = sub.add_parser("pick", help="경쟁 초안 중 다른 초안으로 바꿈 (끝난 race 실행, 바꾸기 전 상태는 브랜치로 남음)")
    _add_workdir(p_pick)
    p_pick.add_argument("--run", metavar="RUN_ID", required=True, help="실행 ID")
    p_pick.add_argument("--draft", required=True, metavar="ROLE", help="고를 초안의 역할 이름 (예: codex)")
    p_pick.set_defaults(func=cmd_pick)
    for name, help_ in (("resolve", "기준 브랜치와의 충돌을 구현 담당에게 풀게 함 (worktree 실행)"),
                        ("notes", "변경 사항의 줄 메모를 구현 담당에게 보내 고치게 함")):
        p_f = sub.add_parser(name, help=help_)
        _add_workdir(p_f)
        p_f.add_argument("--run", metavar="RUN_ID", required=True, help="실행 ID")
        p_f.add_argument("--mock", action="store_true", help="실제 CLI 호출 없이 (기본: 그 실행이 mock 이었는지 따름)")
        p_f.set_defaults(func=cmd_followup, kind=name)

    p_ex = sub.add_parser("explain", help="대화형 세션이 왜 그 상태인지 (맞은 화면 규칙·마지막 훅, DESIGN.md 36.19)")
    p_ex.add_argument("--session", required=True, metavar="ID", help="세션 id (화면 주소 #/s/<id>)")
    p_ex.set_defaults(func=cmd_explain)

    p_wf = sub.add_parser("workflows", help="워크플로 템플릿 목록 / 자세히 보기")
    p_wf.add_argument("action", nargs="?", choices=["list", "show"], default="list", help="list(기본) 또는 show")
    p_wf.add_argument("name", nargs="?", help="show 할 워크플로 이름 또는 @파일경로")
    p_wf.add_argument("--workdir", help="이 프로젝트의 .tenure/workflows/ 도 함께 봄")
    p_wf.set_defaults(func=cmd_workflows)

    p_bench = sub.add_parser("bench", help="벤치마크: 과제 묶음을 워크플로별로 돌려 숨은 테스트로 채점")
    bsub = p_bench.add_subparsers(dest="bench_cmd", metavar="<명령>")
    bsub.required = True
    b_run = bsub.add_parser("run", help="벤치마크 실행 (실제 실행은 --yes 필요)")
    b_run.add_argument("--suite", default="basic", help="과제 묶음: 내장 이름(basic) 또는 폴더 경로")
    b_run.add_argument("--workflow", action="append", metavar="NAME",
                       help="비교할 워크플로 (여러 번 지정 가능, 기본: classic). "
                            "혼자 기준선: solo-claude, solo-codex (DESIGN.md 34장)")
    b_run.add_argument("--task", action="append", metavar="NAME", help="일부 과제만 (여러 번 지정 가능)")
    b_run.add_argument("--repeat", type=int, default=1, help="같은 조합 반복 횟수 (기본 1)")
    b_run.add_argument("--max-review", type=int, help="구현-리뷰 최대 반복 (기본: 과제·설정 값)")
    b_run.add_argument("--out", help="결과 폴더 (기본: ~/.tenure/bench)")
    b_run.add_argument("--wait-on-limit", action="store_true",
                       help="한도에 걸리면 멈추지 않고 재개 시각까지 기다렸다가 이어감")
    b_run.add_argument("--fixed-design", action="store_true",
                       help="과제의 design.md 로 설계 토론을 건너뛰고 모든 워크플로가 같은 설계로 구현부터 (DESIGN.md 31.2)")
    b_run.add_argument("--mock", action="store_true", help="실제 CLI 호출 없이 흐름만 확인")
    b_run.add_argument("--yes", action="store_true", help="실제 구독을 쓰는 실행에 동의")
    b_run.add_argument("--verbose", action="store_true", help="각 실행의 진행 로그도 출력")
    b_run.set_defaults(func=cmd_bench_run)
    b_rep = bsub.add_parser("report", help="결과 폴더의 요약 다시 보기")
    b_rep.add_argument("dir", help="tenure bench run 이 만든 결과 폴더")
    b_rep.set_defaults(func=cmd_bench_report)
    b_list = bsub.add_parser("list", help="과제 묶음과 과제 목록")
    b_list.add_argument("--suite", default="basic", help="과제 묶음 (기본: basic)")
    b_list.set_defaults(func=cmd_bench_list)

    p_ui = sub.add_parser("ui", help="관리자 UI(로컬 웹 대시보드) 실행")
    p_ui.add_argument("--host", default="127.0.0.1", help="바인딩 주소 (기본: 127.0.0.1)")
    p_ui.add_argument("--port", type=int, default=8787, help="포트 (기본: 8787, 사용 중이면 다음 번호)")
    p_ui.add_argument("--workdir", action="append", default=[], metavar="PATH",
                      help="목록에 추가할 작업 폴더 (여러 번 지정 가능)")
    p_ui.add_argument("--new-token", action="store_true",
                      help="접속 토큰을 새로 만든다 (예전 주소·즐겨찾기는 더 이상 열리지 않음)")
    p_ui.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않음")
    p_ui.add_argument("--ready-line", action="store_true", help=argparse.SUPPRESS)   # 데스크톱 셸용 (36.20)
    p_ui.add_argument("--parent-pid", type=int, help=argparse.SUPPRESS)
    p_ui.set_defaults(func=cmd_ui)

    p_doc = sub.add_parser("doctor", help="실행 환경 점검 (git, Claude Code, Codex CLI 설치·로그인)")
    p_doc.add_argument("--json", action="store_true", help="JSON 으로 출력")
    p_doc.set_defaults(func=cmd_doctor)

    # 내부용: 원격 UI 호출, UI 가 띄운 작업의 종료 코드 기록
    p_api = sub.add_parser("_api", help=argparse.SUPPRESS)
    p_api.add_argument("method")
    p_api.set_defaults(func=cmd_api)
    p_job = sub.add_parser("_job", help=argparse.SUPPRESS)
    p_job.add_argument("rc_file")
    p_job.add_argument("rest", nargs=argparse.REMAINDER)
    p_job.set_defaults(func=cmd_job)
    return parser


def _add_workdir(p: argparse.ArgumentParser) -> None:
    p.add_argument("--workdir", required=True, help="프로젝트 디렉터리 (없으면 생성)")


# ---------------------------------------------------------------------- run
def read_task(task: str) -> str:
    if task.startswith("@"):
        path = Path(task[1:]).expanduser()
        if not path.is_file():
            raise OrchestratorError(f"과제 파일을 찾을 수 없습니다: {path}")
        text = path.read_text(encoding="utf-8").strip()
    else:
        text = task.strip()
    if not text:
        raise OrchestratorError("과제가 비어 있습니다.")
    return text


def cmd_run(args: argparse.Namespace) -> int:
    from tenure.options import OptionError, parse_assignments

    try:
        assigned = parse_assignments(args.set)
    except OptionError as e:
        raise OrchestratorError(f"설정 오류: {e}") from e
    explicit = {
        "workflow": args.workflow,
        "implementer": args.implementer, "reviewer": args.reviewer, "synth": args.synth,
        "debate_rounds": args.debate_rounds, "max_review": args.max_review,
        "claude.model": args.claude_model, "claude.effort": args.claude_effort,
        "codex.model": args.codex_model, "codex.effort": args.codex_effort,
        "claude.step_effort": _step_effort(args.claude_step_effort),
        "codex.step_effort": _step_effort(args.codex_step_effort),
        "claude.step_model": _step_effort(args.claude_step_model, parse_step_model),
        "codex.step_model": _step_effort(args.codex_step_model, parse_step_model),
        "step_overrides": _step_effort(args.set_step, parse_set_step),
        "test_command": args.test_command, "block_severity": args.block_severity,
        "stall_rounds": args.stall_rounds,
        "arbiter": False if args.no_arbiter else None,
        "claude_sandbox": True if args.claude_sandbox else None,
        "wait_on_limit": True if args.wait_on_limit else None,
    }
    opts = RunOptions(
        task=read_task(args.task),
        workdir=Path(args.workdir),
        design_only=args.design_only,
        skip_design=args.skip_design,
        mock=args.mock,
        force=args.force,
        # --set 은 고급 설정 (DESIGN.md 28.4). 같은 설정의 전용 플래그를 주면 그쪽이 이긴다
        overrides={**assigned, **{k: v for k, v in explicit.items() if v is not None}},
        attachments=[Path(x) for x in (args.attach or [])],
        run_id=args.run_id,
    )
    return Orchestrator().run(opts).exit_code


def _step_effort(text, parse=parse_step_effort):
    if text is None:
        return None
    try:
        return parse(text)
    except ConfigError as e:
        raise OrchestratorError(f"설정 오류: {e}") from e


def cmd_resume(args: argparse.Namespace) -> int:
    return Orchestrator().resume(Path(args.workdir), args.run, max_review=args.max_review).exit_code


def cmd_report(args: argparse.Namespace) -> int:
    path = Orchestrator().report(Path(args.workdir), args.run, mock=True if args.mock else None)
    if path is None:
        print("결과 요약을 만들지 못했습니다. 위의 로그를 확인하세요.")
        return 1
    print(path.read_text(encoding="utf-8").split("-->", 1)[-1].strip())
    print(f"\n기록: {path}")
    return EXIT_OK


# ---------------------------------------------------------------------- merge (DESIGN.md 36.14)
LEVEL_MARK = {"block": "막음", "warn": "주의", "ok": "통과"}


def cmd_merge(args: argparse.Namespace) -> int:
    from tenure import merge

    project = Path(args.workdir).expanduser().resolve()
    try:
        ready = merge.readiness(project, args.run)
        for c in ready.checks:
            print(f"  [{LEVEL_MARK[c.level]}] {c.label}" + (f" — {c.detail}" if c.detail else ""))
        if args.check:
            print("병합할 수 있습니다." if ready.can_merge else "병합할 수 없습니다.")
            return EXIT_OK if ready.can_merge else 1
        res = merge.merge(project, args.run, args.mode)
    except merge.MergeError as e:
        raise OrchestratorError(str(e)) from e
    print(f"병합함: {res['branch']} → {res['into']} ({res['mode']}, 커밋 {res['commit'][:10]})")
    return EXIT_OK


def cmd_discard(args: argparse.Namespace) -> int:
    from tenure import merge

    try:
        res = merge.discard(Path(args.workdir).expanduser().resolve(), args.run)
    except merge.MergeError as e:
        raise OrchestratorError(str(e)) from e
    print(f"버림: {args.run} (브랜치 {res['branch']} 는 남김)" + (f", 변경은 {res['patch']}" if res["patch"] else ""))
    return EXIT_OK


def cmd_pick(args: argparse.Namespace) -> int:
    from tenure.phases.race import RaceError, pick
    from tenure.worktree import code_dir

    project = Path(args.workdir).expanduser().resolve()
    run_dir = next((d for d in all_run_dirs(project) if d.name == args.run), None)
    if run_dir is None:
        raise OrchestratorError(f"실행 기록을 찾을 수 없습니다: {args.run}")
    try:
        res = pick(code_dir(run_dir), run_dir, args.draft)
    except RaceError as e:
        raise OrchestratorError(str(e)) from e
    print(f"{res['role']} 초안으로 바꿈 ({res['branch']}), 이전 상태는 브랜치 {res['kept']} 에 남김 · 상태 {res['status']}")
    return EXIT_OK


def cmd_explain(args: argparse.Namespace) -> int:
    """세션 기록(출력·훅)으로 상태 판단을 보여 준다. 진행 중인 세션은 UI 서버가 가지므로 여기서는 기록 기준."""
    from tenure.registry import tenure_home
    from tenure.term.session import SessionError, SessionManager

    try:
        s = SessionManager(tenure_home()).get(args.session)
    except SessionError as e:
        raise OrchestratorError(str(e)) from e
    e = s.explain()
    st = e["status"]
    print(f"세션 {s.meta.id} ({s.meta.agent}) · {s.meta.cwd}")
    print(f"  상태: {st['state']} — {st['reason']} (근거: {st['source']})")
    h = e["hook"]
    print(f"  마지막 훅: {h['event']} {h['ts']} → {h['reason']}" if h else "  마지막 훅: 없음")
    r = e["rule"]
    print(f"  맞은 화면 규칙: {r['id']} ({r['source']}) /{r['regex']}/" if r else "  맞은 화면 규칙: 없음")
    print(f"  살펴본 규칙: {', '.join(e['rules'])}")
    print("  화면 끝부분:")
    for ln in (e["tail"] or "(없음)").splitlines():
        print(f"    {ln}")
    return EXIT_OK


def cmd_followup(args: argparse.Namespace) -> int:
    rec = Orchestrator().followup(Path(args.workdir), args.run, args.kind, mock=True if args.mock else None)
    tests = rec.get("tests") or {}
    print(f"후속 라운드 {rec['n']} 끝: 커밋 {rec['commit']}" + (f", 테스트 {tests.get('status')}" if tests else ""))
    return EXIT_OK if not tests or tests.get("status") == "passed" else 1


# ---------------------------------------------------------------------- ui
def cmd_ui(args: argparse.Namespace) -> int:
    from tenure.ui.server import serve

    try:
        serve(args.host, args.port, open_browser=not args.no_browser, extra_projects=args.workdir,
              new_token=args.new_token, ready_line=args.ready_line, parent_pid=args.parent_pid)
    except OSError as e:
        raise OrchestratorError(str(e)) from e
    return EXIT_OK


# ---------------------------------------------------------------------- bench
def cmd_bench_run(args: argparse.Namespace) -> int:
    from tenure.bench import BenchError, load_suite, pick_tasks, run_bench
    from tenure.registry import tenure_home

    workflows = args.workflow or ["classic"]
    if args.repeat < 1:
        raise OrchestratorError("--repeat 는 1 이상이어야 합니다.")
    try:
        tasks = pick_tasks(load_suite(args.suite), args.task)
    except BenchError as e:
        raise OrchestratorError(str(e)) from e
    runs = len(tasks) * len(workflows) * args.repeat
    if not args.mock and not args.yes:
        print(f"실제 Claude·Codex 로 {runs}번 실행합니다 (과제 {len(tasks)}개 × 워크플로 {len(workflows)}개 × "
              f"{args.repeat}회). 실행마다 호출 3~15번, 수 분~20분이 걸리고 구독 사용량을 씁니다.")
        print("계속하려면 --yes 를 붙이세요. 흐름만 보려면 --mock.")
        return EXIT_USAGE
    out = Path(args.out).expanduser() if args.out else tenure_home() / "bench"
    try:
        run_bench(suite=args.suite, workflows=workflows, task_names=args.task, repeat=args.repeat,
                  max_review=args.max_review, out_root=out, mock=args.mock, verbose=args.verbose,
                  wait_on_limit=args.wait_on_limit, fixed_design=args.fixed_design)
    except BenchError as e:
        raise OrchestratorError(str(e)) from e
    return EXIT_OK


def cmd_bench_report(args: argparse.Namespace) -> int:
    from tenure.bench import BenchError, load_results, summarize

    try:
        print(summarize(load_results(Path(args.dir))), end="")
    except BenchError as e:
        raise OrchestratorError(str(e)) from e
    return EXIT_OK


def cmd_bench_list(args: argparse.Namespace) -> int:
    from tenure.bench import BenchError, builtin_suites, load_suite

    print("내장 과제 묶음: " + ", ".join(builtin_suites()))
    try:
        tasks = load_suite(args.suite)
    except BenchError as e:
        raise OrchestratorError(str(e)) from e
    print(f"\n{args.suite}:")
    for t in tasks:
        print(f"  {t.name:<20} [{'기존 프로젝트' if t.kind == 'existing' else '새 프로젝트'}] {t.description}")
    return EXIT_OK


# ---------------------------------------------------------------------- workflows
def cmd_workflows(args: argparse.Namespace) -> int:
    from tenure.config import ConfigError, load_config
    from tenure.workflow import SOURCE_LABELS, WorkflowError, describe, list_workflows, load_workflow

    wd = Path(args.workdir).expanduser().resolve() if args.workdir else None
    try:
        cfg = load_config(wd if wd is not None and wd.is_dir() else None)
    except ConfigError as e:
        raise OrchestratorError(f"설정 오류: {e}") from e
    if args.action == "list":
        print(f"  {'auto':<12} [기본] 자동 선택: 기존 프로젝트·요구가 분명한 일 → quick, 짧고 열린 새 과제 → classic (36.5)")
        for w in list_workflows(wd, cfg):
            if w["source"] == "error":
                print(f"✗ {w['id']:<12} 오류: {w['error']}")
                continue
            print(f"  {w['id']:<12} [{w['source_label']}] {w['description']}")
            print(f"  {'':<12} {w['summary']}")
        print("\n자세히: tenure workflows show <이름>   실행: tenure run ... --workflow <이름>")
        return EXIT_OK
    if not args.name:
        raise OrchestratorError("show 할 워크플로 이름을 주세요: tenure workflows show <이름>")
    try:
        wf = load_workflow(args.name, wd, cfg)
    except WorkflowError as e:
        raise OrchestratorError(f"워크플로 오류: {e}") from e
    d = describe(wf, args.name)
    print(f"{wf.name}  [{SOURCE_LABELS.get(wf.source, wf.source)}]  {wf.path}")
    if wf.description:
        print(f"  {wf.description}")
    print("\n역할:")
    for name in wf.used_roles():
        role = wf.roles[name]
        ac = role.agent_config(cfg)
        from tenure.config import describe_effort

        from tenure.config import describe_model

        extra = [f"모델 {describe_model(ac)}"]
        if describe_effort(ac):
            extra.append(f"강도 {describe_effort(ac)}")
        if role.templates:
            extra.append("템플릿 " + ", ".join(f"{k}={v}" for k, v in role.templates.items()))
        print(f"  {name:<12} {role.agent:<7} {' / '.join(extra)}")
        if role.instructions:
            print(f"  {'':<12} 지시: {_one_line(role.instructions, 90)}")
    print("\n단계:")
    for i, step in enumerate(d["steps"], 1):
        rest = ", ".join(f"{k}={v}" for k, v in step.items() if k not in ("kind", "id"))
        print(f"  {i}. {step['kind']:<8} {rest}")
    return EXIT_OK


# ---------------------------------------------------------------------- doctor / internal
def cmd_doctor(args: argparse.Namespace) -> int:
    from tenure.doctor import format_checks, ready, run_checks

    checks = run_checks()
    if args.json:
        print(json.dumps({"checks": checks, "ready": ready(checks)}, ensure_ascii=False, indent=2))
    else:
        print(format_checks(checks))
        print()
        print("준비됨: 실제 실행이 가능합니다." if ready(checks) else
              "준비 안 됨: 위의 ✗/! 항목을 해결하세요. `tenure ui` 의 '환경·로그인' 화면에서 버튼으로 할 수 있습니다.")
    return EXIT_OK if ready(checks) else EXIT_UNAPPROVED


def cmd_api(args: argparse.Namespace) -> int:
    """원격 UI 호출: stdin 의 JSON 인자 → stdout 한 줄 JSON {"ok": ...} 또는 {"error": ..., "status": ...}"""
    from tenure.ui.dashboard import ApiError, Dashboard, dispatch

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        out: dict = {"ok": dispatch(Dashboard(), args.method, payload)}
    except ApiError as e:
        out = {"error": e.message, "status": e.status}
    except Exception as e:  # noqa: BLE001
        out = {"error": f"원격 오류: {type(e).__name__}: {e}", "status": 500}
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    return EXIT_OK


def cmd_job(args: argparse.Namespace) -> int:
    rest = args.rest[1:] if args.rest[:1] == ["--"] else args.rest
    rc = 1
    try:
        rc = main(rest)
    finally:
        Path(args.rc_file).write_text(str(rc), encoding="utf-8")
    return rc


# ---------------------------------------------------------------------- log
def cmd_log(args: argparse.Namespace) -> int:
    workdir = Path(args.workdir).expanduser().resolve()
    runs = all_run_dirs(workdir)              # worktree 실행 포함 (36.14)
    if not runs:
        print(f"{workdir} 에 실행 기록이 없습니다.")
        return EXIT_USAGE

    if args.all:
        for run_dir in runs:
            st = RunState.load(run_dir)
            print(f"{st.run_id}  {st.status:<20} {st.phase}/{st.step} r{st.round}  {_one_line(st.task)}")
        return EXIT_OK

    if args.run:
        matches = [p for p in runs if p.name == args.run]
        if not matches:
            print(f"실행 기록을 찾을 수 없습니다: {args.run}")
            return EXIT_USAGE
        run_dir = matches[0]
    else:
        run_dir = runs[-1]
    st = RunState.load(run_dir)
    print_summary(st, run_dir)
    if args.full:
        print()
        print_full(run_dir)
    return EXIT_OK


def print_summary(st: RunState, run_dir: Path) -> None:
    c = st.config
    total = sum(x.sec for x in st.calls)
    print(f"실행 {st.run_id}  [{st.status}]")
    print(f"  과제: {_one_line(st.task, 100)}")
    print(f"  위치: {st.phase}/{st.step} round {st.round}   시작 {st.created_at}  갱신 {st.updated_at}")
    if st.workflow:
        from tenure.workflow import Workflow, WorkflowError

        try:
            summary = Workflow.from_dict(st.workflow).summary()
        except WorkflowError:
            summary = "(읽을 수 없음)"
        print(f"  워크플로: {st.workflow.get('name')} — {summary} / "
              f"토론 {c.get('debate_rounds')}라운드 / 리뷰 최대 {c.get('max_review')}회"
              + (" / mock" if c.get("mock") else ""))
    else:
        print(f"  구성: 구현 {c.get('implementer')} / 리뷰 {c.get('reviewer')} / 종합 {c.get('synth')} / "
              f"토론 {c.get('debate_rounds')}라운드 / 리뷰 최대 {c.get('max_review')}회"
              + (" / mock" if c.get("mock") else ""))
    if st.base_commit:
        print(f"  기준 커밋: {st.base_commit}")
    if st.last_verdict:
        print(f"  마지막 판정: {st.last_verdict}  ({st.last_review})")
    if st.error:
        print(f"  오류: {st.error}")
    print(f"  호출 {len(st.calls)}회, 총 {total:.0f}초")
    for i, call in enumerate(st.calls, 1):
        flag = " 한도" if call.rate_limited else (" 시간초과" if call.timed_out else ("" if call.exit == 0 else f" exit {call.exit}"))
        who = f"{call.role}({call.agent})" if call.role else call.agent
        print(f"    {i:2d}. {who:<7} {call.step:<10} {call.sec:7.1f}초{flag}  {call.file or ''}")
    print(f"  기록: {run_dir}")


def print_full(run_dir: Path) -> None:
    for e in Transcript(run_dir).entries():
        m = e.meta
        who = f"{m['role']}({m.get('agent', '?')})" if m.get("role") else m.get("agent", "?")
        head = f"{e.name}  [{who} · {m.get('step', '?')} · {m.get('mode', '?')} · {m.get('duration_sec', '?')}초]"
        print("=" * 78)
        print(head)
        print("=" * 78)
        print(e.body().rstrip())
        print()


def _one_line(text: str, limit: int = 60) -> str:
    s = " ".join(text.split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


# ---------------------------------------------------------------------- main
def _sigterm_as_interrupt(signum: int, frame: object) -> None:
    # UI 의 '중지' 는 SIGTERM 을 보낸다. Ctrl-C 와 같은 경로(KeyboardInterrupt)로 처리해
    # 진행 중인 claude/codex 프로세스 그룹을 정리하고 상태를 stopped_user 로 저장한다.
    raise KeyboardInterrupt


def _utf8_output() -> None:
    """표준 출력이 UTF-8 이 아니면 UTF-8 로 쓴다 (Windows 의 cp949 에서 이모지·— 로 죽지 않게, UI 는 로그를 UTF-8 로 읽는다).

    isatty 로 거르지 않는다: Windows 의 NUL 장치는 isatty() 가 참이라 걸러지면 cp949 로 남는다.
    진짜 콘솔은 파이썬이 이미 UTF-8 로 연다.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if (stream.encoding or "").lower().replace("-", "") != "utf8":
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: Sequence[str] | None = None) -> int:
    _utf8_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    previous = None
    try:
        previous = signal.signal(signal.SIGTERM, _sigterm_as_interrupt)
        if hasattr(signal, "SIGBREAK"):           # Windows 콘솔의 Ctrl-Break
            signal.signal(signal.SIGBREAK, _sigterm_as_interrupt)
    except ValueError:  # 메인 스레드가 아님
        previous = None
    try:
        return args.func(args)
    except OrchestratorError as e:
        print(f"오류: {e}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("\n중단됨. `tenure resume` 으로 이어서 실행할 수 있습니다.", file=sys.stderr)
        return 130
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    sys.exit(main())
