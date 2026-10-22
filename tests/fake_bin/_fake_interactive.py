"""가짜 대화형 CLI (M34 테스트·화면 확인용, DESIGN.md 36.19).

진짜 claude·codex 를 띄우지 않고 세션·훅·화면 규칙·입력을 끝까지 확인한다.
- claude: `--settings <JSON>` 의 훅을 실제로 부른다(SessionStart·UserPromptSubmit·Notification·Stop).
- codex: `-c notify=[...]` 의 명령을 턴이 끝날 때 JSON 을 붙여 부른다.
- 줄에 '권한'·'permission' 이 있으면 승인 질문을 그리고 답을 기다린다.
- 'exit' 면 끝난다.
"""
import json
import subprocess
import sys
import time
import tomllib

PASTE = ("\x1b[200~", "\x1b[201~")


def _hook_claude(settings: dict, event: str, payload: dict) -> None:
    for group in (settings.get("hooks") or {}).get(event) or []:
        for h in group.get("hooks") or []:
            subprocess.run(h["command"], shell=True, input=json.dumps({"hook_event_name": event, **payload}),
                           text=True, timeout=20)


def _hook_codex(notify: list, payload: dict) -> None:
    if notify:
        subprocess.run([*notify, json.dumps(payload)], timeout=20)


def _out(s: str) -> None:
    sys.stdout.write(s)
    sys.stdout.flush()


def _line() -> str | None:
    line = sys.stdin.readline()
    if not line:
        return None
    for m in PASTE:
        line = line.replace(m, "")
    return line.strip("\r\n")


def _key() -> str:
    """키 하나 (진짜 codex 의 승인처럼 Enter 없이)."""
    if sys.platform == "win32":
        import msvcrt
        return msvcrt.getwch()
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def run(agent: str, argv: list[str]) -> int:
    settings, notify = {}, []
    if "--settings" in argv:
        settings = json.loads(argv[argv.index("--settings") + 1])
    for i, a in enumerate(argv):
        if a == "-c" and i + 1 < len(argv) and argv[i + 1].startswith("notify="):
            notify = tomllib.loads("x = " + argv[i + 1][len("notify="):])["x"]
    claude = agent == "claude"
    _out("\x1b[?2004h")                                  # bracketed paste 켬
    _out(f"가짜 {agent} 대화형 (exit 로 끝냄)\r\n")
    if claude:
        _hook_claude(settings, "SessionStart", {"source": "startup"})
    while True:
        _out("\r\n> ")
        line = _line()
        if line is None or line.strip() == "exit":
            _out("\r\n끝\r\n")
            return 0
        if claude:
            _hook_claude(settings, "UserPromptSubmit", {"prompt": line})
        _out("\r\n작업 중... (esc to interrupt)\r\n")
        time.sleep(0.3)
        if "권한" in line or "permission" in line.lower():
            if claude:
                _out("Bash 명령: rm -rf build\r\nDo you want to proceed?\r\n❯ 1. Yes\r\n  2. No\r\n")
                _hook_claude(settings, "Notification", {"notification_type": "permission_prompt",
                                                         "message": "Claude needs your permission to use Bash"})
                ans = _line()
                ok = ans is not None and (ans.strip() in ("", "1", "y", "Y"))
            else:
                _out("Allow command? rm -rf build (y = 승인, Esc = 거절)\r\n")
                ok = _key() in ("y", "Y")
            _out("\r\n승인됨: 실행했습니다\r\n" if ok else "\r\n거절됨: 실행하지 않았습니다\r\n")
            time.sleep(0.3)
        _out(f"완료: {line}\r\n")
        if claude:
            _hook_claude(settings, "Stop", {"stop_hook_active": False})
        else:
            _hook_codex(notify, {"type": "agent-turn-complete", "last-assistant-message": f"완료: {line}"})
