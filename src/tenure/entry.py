"""실행 진입점 (`python -m tenure`, 얼린 엔진 공통, DESIGN.md 36.20).

무거운 tenure.cli 를 불러오기 전에 빨리 끝나야 하는 숨은 명령을 먼저 처리한다.
- `_hook <세션 폴더> <nonce> <이벤트> [JSON]`: 대화형 세션 훅 (CLI 가 기다린다, 36.19)
- `_pick <시작 폴더>`: OS 폴더 고르기 창 (얼린 엔진에는 `python -c` 가 없다)
- `_http <포트>`: 브라우저 확인의 정적 서버 (`python -m http.server` 대신)
"""

from __future__ import annotations

import sys


def run(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    if cmd == "_hook" and len(argv) >= 4:
        from tenure.term.hooks import CODEX_EVENT, chain_notify, record

        d, nonce, event = argv[1], argv[2], argv[3]
        payload = argv[4] if len(argv) > 4 else (sys.stdin.read() if sys.stdin and not sys.stdin.isatty() else "")
        try:
            record(d, nonce, event, payload)
        except OSError:
            pass
        if event == CODEX_EVENT:
            chain_notify(payload)                # 사용자의 원래 notify 도 부른다
        return 0
    if cmd == "_pick":
        from tenure.ui.pick import pick_folder

        sys.stdout.write(pick_folder(argv[1] if len(argv) > 1 else ""))
        return 0
    if cmd == "_http" and len(argv) >= 2:
        import http.server

        http.server.test(HandlerClass=http.server.SimpleHTTPRequestHandler, port=int(argv[1]), bind="127.0.0.1")
        return 0
    from tenure.cli import main

    return main(argv)
