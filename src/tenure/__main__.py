import sys

if len(sys.argv) >= 5 and sys.argv[1] == "_hook":
    # 세션 훅 (DESIGN.md 36.19): CLI 가 기다리므로 무거운 tenure.cli 를 불러오지 않고 바로 쓴다
    from tenure.term.hooks import CODEX_EVENT, chain_notify, record

    _dir, _nonce, _event = sys.argv[2], sys.argv[3], sys.argv[4]
    _payload = sys.argv[5] if len(sys.argv) > 5 else (sys.stdin.read() if not sys.stdin.isatty() else "")
    try:
        record(_dir, _nonce, _event, _payload)
    except OSError:
        pass
    if _event == CODEX_EVENT:
        chain_notify(_payload)                 # 사용자의 원래 notify 도 부른다
    sys.exit(0)

from tenure.cli import main  # noqa: E402

sys.exit(main())
