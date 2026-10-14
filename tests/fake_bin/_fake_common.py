"""가짜 claude/codex 실행 파일 공통부. 표준 라이브러리만, Python 3.8+ 호환.

환경변수:
  DUET_FAKE_DUMP      받은 argv/stdin/cwd를 JSON으로 쓸 파일 경로
  DUET_FAKE_SCENARIO  ok(기본) | fail | rate_limit | hang | garbage | empty
  DUET_FAKE_TEXT      응답 본문 (기본 "fake response")
  DUET_FAKE_SLEEP     hang 시나리오에서 잠들 초 (기본 30)
"""
import json
import os
import sys
import time


def dump(argv, stdin_text):
    path = os.environ.get("DUET_FAKE_DUMP")
    if not path:
        return
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {"argv": argv, "stdin": stdin_text, "cwd": os.getcwd()},
            f, ensure_ascii=False, indent=1,
        )


def read_stdin_if_piped():
    if sys.stdin is None or sys.stdin.isatty():
        return None
    data = sys.stdin.read()
    return data if data else None


def scenario():
    return os.environ.get("DUET_FAKE_SCENARIO", "ok")


def text():
    return os.environ.get("DUET_FAKE_TEXT", "fake response")


def handle_common_failures():
    """ok/garbage/empty 이외의 시나리오를 처리하고 종료. 반환하면 정상 진행."""
    s = scenario()
    if s == "fail":
        sys.stderr.write("fake: something went wrong\n")
        sys.exit(1)
    if s == "rate_limit":
        sys.stderr.write("Error: You've hit your usage limit. Try again later.\n")
        sys.exit(1)
    if s == "hang":
        time.sleep(float(os.environ.get("DUET_FAKE_SLEEP", "30")))
        sys.exit(0)
