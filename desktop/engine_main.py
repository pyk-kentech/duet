"""데스크톱 앱 엔진(sidecar)의 진입점 (DESIGN.md 36.20). PyInstaller 가 이 파일로 tenure-engine.exe 를 만든다."""

import sys

from tenure.entry import run

if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
