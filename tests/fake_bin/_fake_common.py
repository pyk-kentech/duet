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


def write_rollout(argv):
    """CODEX_HOME 이 있으면 진짜 codex 처럼 세션 기록을 남긴다(사용량·한도 테스트용)."""
    import datetime as dt
    home = os.environ.get("CODEX_HOME")
    if not home:
        return
    cwd = argv[argv.index("-C") + 1] if "-C" in argv else os.getcwd()
    model = argv[argv.index("-m") + 1] if "-m" in argv else "gpt-fake"
    now = dt.datetime.now()
    folder = os.path.join(home, "sessions", f"{now:%Y}", f"{now:%m}", f"{now:%d}")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"rollout-{now:%Y-%m-%dT%H-%M-%S}-{os.getpid()}.jsonl")
    ts = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    events = [
        {"timestamp": ts, "type": "session_meta", "payload": {"cwd": os.path.realpath(cwd), "originator": "codex_exec", "timestamp": ts}},
        {"timestamp": ts, "type": "turn_context", "payload": {"cwd": cwd, "model": model, "effort": "high"}},
        {"timestamp": ts, "type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": 2000, "cached_input_tokens": 1500, "output_tokens": 300, "reasoning_output_tokens": 120}},
            "rate_limits": {"primary": {"used_percent": 42.5, "window_minutes": 10080, "resets_at": 1792472350},
                            "secondary": None, "plan_type": "pro"}}},
    ]
    with open(path, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
