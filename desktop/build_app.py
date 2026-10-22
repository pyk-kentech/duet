"""데스크톱 앱 전체 빌드 (DESIGN.md 36.20): 화면 → 엔진(얼림) → Tauri 설치 파일 → 업데이트용 latest.json.

    python desktop/build_app.py

필요: Node, Rust(rustup, MSVC), VS C++ 빌드 도구, `pip install -e ".[desktop]"`.
업데이트 서명: 비밀 키 `~/.tauri/tenure.key` (없으면 서명 없이 빌드하고 업데이트 파일은 만들지 않는다).
결과: app/src-tauri/target/release/bundle/nsis/ 의 설치 파일, .sig, latest.json.
GitHub 릴리스에 올리는 일은 이 스크립트가 하지 않는다(올릴 때 사람이 정한다).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
TAURI = APP / "src-tauri"
KEY = Path.home() / ".tauri" / "tenure.key"
REPO = "pyk-kentech/duet"


def versions() -> dict[str, str]:
    py = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    conf = json.loads((TAURI / "tauri.conf.json").read_text(encoding="utf-8"))["version"]
    cargo = tomllib.loads((TAURI / "Cargo.toml").read_text(encoding="utf-8"))["package"]["version"]
    return {"pyproject.toml": py, "tauri.conf.json": conf, "Cargo.toml": cargo}


def run(cmd: list[str], cwd: Path, env: dict | None = None) -> None:
    print("$", " ".join(cmd), flush=True)
    exe = shutil.which(cmd[0], path=(env or os.environ).get("PATH")) or cmd[0]
    subprocess.run([exe, *cmd[1:]], cwd=cwd, env=env, check=True)


def latest_json(version: str, bundle: Path) -> Path | None:
    setup = next(bundle.glob(f"*_{version}_*-setup.exe"), None)
    sig = setup.with_name(setup.name + ".sig") if setup else None
    if not setup or not sig or not sig.is_file():
        print("업데이트 서명 파일이 없어 latest.json 을 만들지 않습니다.")
        return None
    data = {"version": version, "notes": f"tenure {version}", "pub_date": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "platforms": {"windows-x86_64": {"signature": sig.read_text(encoding="utf-8").strip(),
                                             "url": f"https://github.com/{REPO}/releases/download/v{version}/{setup.name}"}}}
    out = bundle / "latest.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> None:
    v = versions()
    if len(set(v.values())) != 1:
        sys.exit(f"버전이 서로 다릅니다: {v}. 세 파일을 같은 버전으로 맞추세요.")
    version = next(iter(v.values()))
    env = {**os.environ, "PATH": str(Path.home() / ".cargo" / "bin") + os.pathsep + os.environ.get("PATH", "")}
    if KEY.is_file():
        env.setdefault("TAURI_SIGNING_PRIVATE_KEY", str(KEY))
        env.setdefault("TAURI_SIGNING_PRIVATE_KEY_PASSWORD", "")
    else:
        print(f"서명 키가 없습니다({KEY}). 업데이트 파일 없이 빌드합니다.")
    run(["npm", "run", "build"], APP)                                     # 화면 → src/tenure/ui/web
    run([sys.executable, str(ROOT / "desktop" / "build_engine.py")], ROOT)  # 엔진 → app/src-tauri/engine
    run(["npx", "tauri", "build"], APP, env)
    bundle = TAURI / "target" / "release" / "bundle" / "nsis"
    lj = latest_json(version, bundle)
    print(f"\n설치 파일: {bundle}")
    for f in sorted(bundle.iterdir()):
        print(f"  {f.name}  {f.stat().st_size / 1e6:.1f}MB")
    if lj:
        print(f"릴리스에 올릴 것: 설치 파일, .sig, latest.json (태그 v{version})")


if __name__ == "__main__":
    main()
