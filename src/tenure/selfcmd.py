"""tenure 가 자기 자신을 다시 부르는 명령 (DESIGN.md 36.20).

- 보통: `python -m tenure ...`
- 얼린 엔진(데스크톱 앱의 sidecar, PyInstaller): 실행 파일 그대로 `tenure-engine.exe ...`
- zip(tenure.pyz)으로 돌 때: `python tenure.pyz ...` (원격 머신 배포, DESIGN.md 27장)
"""

from __future__ import annotations

import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))


def self_argv(*args: str) -> list[str]:
    if FROZEN:
        return [sys.executable, *args]
    import tenure

    f = str(Path(tenure.__file__))
    if ".pyz" in f:
        return [sys.executable, f[: f.index(".pyz") + 4], *args]
    return [sys.executable, "-m", "tenure", *args]
