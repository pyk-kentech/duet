"""엔진 sidecar 를 얼린다 (DESIGN.md 36.20): PyInstaller onedir → app/src-tauri/engine/.

    python desktop/build_engine.py            # 빌드 + 간단한 확인
    python desktop/build_engine.py --check    # 이미 만든 것만 확인

필요: `pip install -e ".[desktop]"` (PyInstaller). 결과는 저장소에 넣지 않는다(.gitignore).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "desktop"
STAGE = BUILD / "stage"
DIST = BUILD / "dist"
TARGET = ROOT / "app" / "src-tauri" / "engine"
NAME = "tenure-engine"
EXE = TARGET / (NAME + (".exe" if sys.platform == "win32" else ""))


def stage_sources() -> Path:
    """tenure 패키지 원본을 데이터로도 넣는다: 템플릿·워크플로·벤치마크 과제·화면, 그리고 원격 배포(tenure.pyz)용 소스."""
    dst = STAGE / "tenure"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(ROOT / "src" / "tenure", dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return dst


def build() -> None:
    try:
        import PyInstaller.__main__ as pyi
    except ImportError:
        sys.exit('PyInstaller 가 없습니다. 먼저: pip install -e ".[desktop]"')
    src = stage_sources()
    sep = ";" if sys.platform == "win32" else ":"
    args = [
        str(ROOT / "desktop" / "engine_main.py"),
        "--name", NAME, "--onedir", "--noconfirm", "--clean", "--console",
        "--distpath", str(DIST), "--workpath", str(BUILD / "work"), "--specpath", str(BUILD),
        "--paths", str(ROOT / "src"),
        "--collect-submodules", "tenure",          # 안에서 늦게 불러오는 모듈이 많다
        "--hidden-import", "tkinter", "--hidden-import", "tkinter.filedialog",
        "--add-data", f"{src}{sep}tenure",
    ]
    if sys.platform == "win32":
        args += ["--collect-all", "winpty"]       # ConPTY (pywinpty 의 DLL·실행 파일)
    pyi.run(args)
    if TARGET.exists():
        shutil.rmtree(TARGET)
    shutil.copytree(DIST / NAME, TARGET)
    print(f"엔진: {TARGET}")


def check() -> None:
    """얼린 엔진이 숨은 명령·UI 서버를 띄울 수 있는지 본다 (진짜 claude·codex 는 부르지 않는다)."""
    if not EXE.is_file():
        sys.exit(f"엔진이 없습니다: {EXE} (먼저 빌드)")
    tmp = BUILD / "check-home"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    env = {**os.environ, "TENURE_HOME": str(tmp)}
    r = subprocess.run([str(EXE), "_hook", str(tmp), "n1", "Stop"], input='{"hook_event_name":"Stop"}', text=True,
                       capture_output=True, timeout=60, env=env)
    assert r.returncode == 0 and (tmp / "hooks.jsonl").is_file(), r.stderr
    print("  _hook: 됨")
    p = subprocess.Popen([str(EXE), "ui", "--no-browser", "--port", "0", "--ready-line"], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", env=env)
    try:
        deadline = time.monotonic() + 60
        url = None
        while time.monotonic() < deadline and p.stdout is not None:
            line = p.stdout.readline()
            if line.startswith("TENURE_READY "):
                url = json.loads(line[len("TENURE_READY "):])["url"]
                break
            if not line and p.poll() is not None:
                break
        assert url, "TENURE_READY 를 받지 못했습니다"
        with urllib.request.urlopen(url, timeout=20) as resp:
            html = resp.read().decode("utf-8")
        assert 'name="tenure-token"' in html
        print(f"  ui: 됨 ({url.split('?')[0]})")
    finally:
        p.terminate()
        p.wait(10)
    size = sum(f.stat().st_size for f in TARGET.rglob("*") if f.is_file()) / 1e6
    print(f"  크기: {size:.0f}MB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="빌드하지 않고 확인만")
    a = ap.parse_args()
    if not a.check:
        build()
    check()
