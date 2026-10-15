"""duet 명령줄 진입점. 서브커맨드: run / resume / log"""

from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path
from typing import Sequence

from duet import __version__
from duet.orchestrator import Orchestrator, OrchestratorError, RunOptions
from duet.state import RunState, latest_run_dir, list_run_dirs
from duet.transcript import Transcript

EXIT_OK = 0
EXIT_UNAPPROVED = 1
EXIT_USAGE = 2
EXIT_STOPPED = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="duet",
        description="Claude Code와 Codex CLI가 설계를 토론하고 서로의 코드를 교차 리뷰하는 도구",
    )
    parser.add_argument("--version", action="version", version=f"duet {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    p_run = sub.add_parser("run", help="설계 토론 → 구현 → 교차 리뷰를 처음부터 실행")
    p_run.add_argument("task", help="만들 것 (한 줄 설명, 또는 @파일경로로 긴 설명)")
    _add_workdir(p_run)
    p_run.add_argument("--mock", action="store_true", help="실제 CLI 호출 없이 흐름만 테스트")
    p_run.add_argument("--implementer", choices=["claude", "codex"], help="구현 담당 (기본: claude)")
    p_run.add_argument("--reviewer", choices=["claude", "codex"], help="리뷰 담당 (기본: codex)")
    p_run.add_argument("--synth", choices=["claude", "codex"], help="최종 설계 종합 담당 (기본: 리뷰어)")
    p_run.add_argument("--debate-rounds", type=int, help="설계 토론 비판 라운드 수 (기본: 1, 최대 5)")
    p_run.add_argument("--max-review", type=int, help="구현-리뷰 최대 반복 (기본: 3, 최대 10)")
    p_run.add_argument("--design-only", action="store_true", help="설계 토론만 하고 종료")
    p_run.add_argument("--skip-design", action="store_true", help="기존 DESIGN.md로 바로 구현")
    p_run.add_argument("--force", action="store_true", help="커밋 안 된 변경이 있어도 진행")
    for agent, example in (("claude", "opus, sonnet, claude-opus-5-5"), ("codex", "gpt-6.1-sol")):
        p_run.add_argument(f"--{agent}-model", metavar="MODEL", help=f"{agent} 모델 (예: {example}). 기본: CLI 기본값")
        p_run.add_argument(f"--{agent}-effort", metavar="LEVEL", help=f"{agent} 추론 강도 (예: low, medium, high, xhigh)")
    p_run.set_defaults(func=cmd_run)

    p_resume = sub.add_parser("resume", help="중단된 마지막 실행을 이어서 진행")
    _add_workdir(p_resume)
    p_resume.add_argument("--run", metavar="RUN_ID", help="특정 실행 ID (기본: 마지막 실행)")
    p_resume.add_argument("--max-review", type=int,
                          help="구현-리뷰 상한을 늘려서 이어감 (미승인으로 끝난 실행을 계속할 때 필요, 최대 10)")
    p_resume.set_defaults(func=cmd_resume)

    p_log = sub.add_parser("log", help="지난 실행 기록 보기")
    _add_workdir(p_log)
    p_log.add_argument("--full", action="store_true", help="전체 발언을 순서대로 출력")
    p_log.add_argument("--run", metavar="RUN_ID", help="특정 실행 ID (기본: 마지막 실행)")
    p_log.add_argument("--all", action="store_true", help="모든 실행을 한 줄씩 나열")
    p_log.set_defaults(func=cmd_log)

    p_ui = sub.add_parser("ui", help="관리자 UI(로컬 웹 대시보드) 실행")
    p_ui.add_argument("--host", default="127.0.0.1", help="바인딩 주소 (기본: 127.0.0.1)")
    p_ui.add_argument("--port", type=int, default=8787, help="포트 (기본: 8787, 사용 중이면 다음 번호)")
    p_ui.add_argument("--workdir", action="append", default=[], metavar="PATH",
                      help="목록에 추가할 작업 폴더 (여러 번 지정 가능)")
    p_ui.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않음")
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
    opts = RunOptions(
        task=read_task(args.task),
        workdir=Path(args.workdir),
        design_only=args.design_only,
        skip_design=args.skip_design,
        mock=args.mock,
        force=args.force,
        overrides={
            "implementer": args.implementer, "reviewer": args.reviewer, "synth": args.synth,
            "debate_rounds": args.debate_rounds, "max_review": args.max_review,
            "claude.model": args.claude_model, "claude.effort": args.claude_effort,
            "codex.model": args.codex_model, "codex.effort": args.codex_effort,
        },
    )
    return Orchestrator().run(opts).exit_code


def cmd_resume(args: argparse.Namespace) -> int:
    return Orchestrator().resume(Path(args.workdir), args.run, max_review=args.max_review).exit_code


# ---------------------------------------------------------------------- ui
def cmd_ui(args: argparse.Namespace) -> int:
    from duet.ui.server import serve

    try:
        serve(args.host, args.port, open_browser=not args.no_browser, extra_projects=args.workdir)
    except OSError as e:
        raise OrchestratorError(str(e)) from e
    return EXIT_OK


# ---------------------------------------------------------------------- doctor / internal
def cmd_doctor(args: argparse.Namespace) -> int:
    from duet.doctor import format_checks, ready, run_checks

    checks = run_checks()
    if args.json:
        print(json.dumps({"checks": checks, "ready": ready(checks)}, ensure_ascii=False, indent=2))
    else:
        print(format_checks(checks))
        print()
        print("준비됨: 실제 실행이 가능합니다." if ready(checks) else
              "준비 안 됨: 위의 ✗/! 항목을 해결하세요. `duet ui` 의 '환경·로그인' 화면에서 버튼으로 할 수 있습니다.")
    return EXIT_OK if ready(checks) else EXIT_UNAPPROVED


def cmd_api(args: argparse.Namespace) -> int:
    """원격 UI 호출: stdin 의 JSON 인자 → stdout 한 줄 JSON {"ok": ...} 또는 {"error": ..., "status": ...}"""
    from duet.ui.dashboard import ApiError, Dashboard, dispatch

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
    runs = list_run_dirs(workdir)
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
        run_dir = latest_run_dir(workdir)
        assert run_dir is not None
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
        print(f"    {i:2d}. {call.agent:<7} {call.step:<10} {call.sec:7.1f}초{flag}  {call.file or ''}")
    print(f"  기록: {run_dir}")


def print_full(run_dir: Path) -> None:
    for e in Transcript(run_dir).entries():
        m = e.meta
        head = f"{e.name}  [{m.get('agent', '?')} · {m.get('step', '?')} · {m.get('mode', '?')} · {m.get('duration_sec', '?')}초]"
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    previous = None
    try:
        previous = signal.signal(signal.SIGTERM, _sigterm_as_interrupt)
    except ValueError:  # 메인 스레드가 아님
        previous = None
    try:
        return args.func(args)
    except OrchestratorError as e:
        print(f"오류: {e}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("\n중단됨. `duet resume` 으로 이어서 실행할 수 있습니다.", file=sys.stderr)
        return 130
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    sys.exit(main())
