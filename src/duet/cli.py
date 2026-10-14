"""duet 명령줄 진입점.

서브커맨드: run / resume / log
M0에서는 인자 파싱과 골격만 제공하며, 실제 동작은 이후 마일스톤에서 채운다.
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from duet import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="duet",
        description="Claude Code와 Codex CLI가 설계를 토론하고 서로의 코드를 교차 리뷰하는 도구",
    )
    parser.add_argument("--version", action="version", version=f"duet {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # run
    p_run = sub.add_parser("run", help="설계 토론 → 구현 → 교차 리뷰를 처음부터 실행")
    p_run.add_argument("task", help="만들 것 (한 줄 설명, 또는 @파일경로로 긴 설명)")
    _add_common(p_run)
    p_run.add_argument("--implementer", choices=["claude", "codex"], help="구현 담당 (기본: claude)")
    p_run.add_argument("--reviewer", choices=["claude", "codex"], help="리뷰 담당 (기본: codex)")
    p_run.add_argument("--synth", choices=["claude", "codex"], help="최종 설계 종합 담당 (기본: 리뷰어)")
    p_run.add_argument("--debate-rounds", type=int, help="설계 토론 비판 라운드 수 (기본: 1, 최대 5)")
    p_run.add_argument("--max-review", type=int, help="구현-리뷰 최대 반복 (기본: 3, 최대 10)")
    p_run.add_argument("--design-only", action="store_true", help="설계 토론만 하고 종료")
    p_run.add_argument("--skip-design", action="store_true", help="기존 DESIGN.md로 바로 구현")
    p_run.add_argument("--force", action="store_true", help="커밋 안 된 변경이 있어도 진행")
    p_run.set_defaults(func=cmd_run)

    # resume
    p_resume = sub.add_parser("resume", help="중단된 마지막 실행을 이어서 진행")
    _add_common(p_resume)
    p_resume.set_defaults(func=cmd_resume)

    # log
    p_log = sub.add_parser("log", help="지난 실행 기록 보기")
    p_log.add_argument("--workdir", required=True, help="프로젝트 디렉터리")
    p_log.add_argument("--full", action="store_true", help="전체 발언을 순서대로 출력")
    p_log.set_defaults(func=cmd_log)

    return parser


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--workdir", required=True, help="프로젝트 디렉터리 (없으면 생성)")
    p.add_argument("--mock", action="store_true", help="실제 CLI 호출 없이 흐름만 테스트")


def cmd_run(args: argparse.Namespace) -> int:
    print("아직 구현되지 않았습니다: run (M5에서 완성)", file=sys.stderr)
    return 2


def cmd_resume(args: argparse.Namespace) -> int:
    print("아직 구현되지 않았습니다: resume (M5에서 완성)", file=sys.stderr)
    return 2


def cmd_log(args: argparse.Namespace) -> int:
    print("아직 구현되지 않았습니다: log (M5에서 완성)", file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
