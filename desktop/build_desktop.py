"""데스크톱 앱 설치 파일을 만든다 (DESIGN.md 36.23 M40): 엔진 화면 → 엔진 얼리기 → 오르카 포크 설치 파일.

    python desktop/build_desktop.py

필요한 것: app/ 의 npm 의존성, pip install -e ".[desktop]" (PyInstaller), 오르카 포크 `orca/` 와
휴대용 Node 24 `.tools/node24` (pnpm 은 corepack). 결과: orca/dist/ 의 tenure-<버전>-setup 설치 파일.
설치 파일은 서명하지 않는다(SmartScreen 경고가 뜰 수 있다). 업데이트는 아직 꺼져 있다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
ORCA = ROOT / "orca"
NODE24 = ROOT / ".tools" / "node24"
REVISION_FILE = ROOT / "desktop" / "desktop-revision.txt"


def desktop_version() -> str:
    """앱 버전 = 오르카 버전의 끝자리 x100 + tenure 회차 (예: 1.4.214 + 1 → 1.4.21401). 오르카가 올라가도 계속 커진다."""
    major, minor, patch = json.loads((ORCA / "package.json").read_text(encoding="utf-8"))["version"].split("-")[0].split(".")
    rev = int(REVISION_FILE.read_text(encoding="utf-8").strip() or "0")
    return f"{major}.{minor}.{int(patch) * 100 + rev}"


def run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    print(f"$ {' '.join(cmd)}  ({cwd.name})", flush=True)
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def main() -> None:
    if not ORCA.is_dir():
        sys.exit(f"오르카 포크가 없습니다: {ORCA} (DESIGN.md 36.23)")
    if not (NODE24 / ("node.exe" if sys.platform == "win32" else "node")).is_file():
        sys.exit(f"Node 24 가 없습니다: {NODE24}")
    npm = shutil.which("npm") or "npm"
    run([npm, "run", "build"], APP)                                           # 엔진 화면 → src/tenure/ui/web (섬 화면 포함)
    run([sys.executable, str(ROOT / "desktop" / "build_engine.py")], ROOT)    # 엔진 → build/desktop/dist/tenure-engine
    env = {**os.environ, "PATH": f"{NODE24}{os.pathsep}{os.environ.get('PATH', '')}",
           "COREPACK_HOME": str(ROOT / ".tools" / "corepack"), "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0",
           "ORCA_LOCAL_BUILD_VERSION": desktop_version()}
    print(f"데스크톱 앱 버전: {env['ORCA_LOCAL_BUILD_VERSION']}")
    pnpm = str(NODE24 / ("pnpm.cmd" if sys.platform == "win32" else "pnpm"))
    if not (ORCA / "mobile" / "node_modules").is_dir():                       # 설치 파일 단계가 모바일 웹 묶음을 검사한다
        run([pnpm, "install", "--frozen-lockfile"], ORCA / "mobile", env)
    target = {"win32": "build:win", "darwin": "build:mac"}.get(sys.platform, "build:linux")
    run([pnpm, "run", target], ORCA, env)
    dist = ORCA / "dist"
    print("\n설치 파일:")
    for f in sorted(dist.glob("*")):
        if f.is_file() and f.suffix.lower() in (".exe", ".dmg", ".appimage", ".deb"):
            print(f"  {f}  {f.stat().st_size / 1e6:.1f}MB")


if __name__ == "__main__":
    main()
