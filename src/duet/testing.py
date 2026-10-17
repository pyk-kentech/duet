"""구현 후 duet 가 직접 돌리는 테스트.

명령 결정 순서: 명시값(CLI·설정, "auto"/"" 가 아닌 것) → 작업 폴더 duet.toml 의 test_command
(구현자가 적을 수 있다) → 프로젝트 파일로 자동 감지. "none" 이면 테스트를 하지 않는다.
"""

from __future__ import annotations

import json
import re
import shutil
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Collection

from duet import procs
from duet.runner import augmented_path, run_process
import os

OUTPUT_TAIL = 6000
# 명령이 없거나 실행 불가, pytest 의 '수집된 테스트 없음' 은 코드 결함이 아니라 판정을 막지 않는다
NOT_RUNNABLE_EXITS = {126, 127}
PYTEST_NO_TESTS = 5


@dataclass
class TestResult:
    command: str
    source: str            # "설정" | "duet.toml" | "자동 감지"
    status: str            # passed | failed | error | timeout
    exit_code: int
    duration_sec: float
    summary: str
    output_tail: str

    @property
    def blocks_approval(self) -> bool:
        return self.status in ("failed", "timeout")

    def to_dict(self) -> dict:
        return asdict(self)


def resolve_command(workdir: Path, configured: str) -> tuple[str, str] | None:
    """(명령, 출처) 또는 None(테스트 안 함)."""
    c = (configured or "auto").strip()
    if c.lower() == "none":
        return None
    v = _toml_test_command(workdir)
    if c.lower() != "auto":
        # 작업 폴더 duet.toml 의 값은 설정 층으로도 읽힌다. 같은 값이면 출처를 duet.toml 로 (DESIGN.md 19.7)
        return c, "duet.toml" if v is not None and v.strip() == c else "설정"
    if v is not None and v.strip():
        if v.strip().lower() == "none":
            return None
        if v.strip().lower() != "auto":
            return v.strip(), "duet.toml"
    detected = detect_command(workdir)
    return (detected, "자동 감지") if detected else None


def _toml_test_command(workdir: Path) -> str | None:
    toml = workdir / "duet.toml"
    if not toml.is_file():
        return None
    try:
        v = tomllib.loads(toml.read_text(encoding="utf-8")).get("test_command")
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return v if isinstance(v, str) else None


def _has_tool(name: str) -> bool:
    return shutil.which(name, path=augmented_path(os.environ.get("PATH"))) is not None


def detect_command(wd: Path) -> str | None:
    py_markers = ("pyproject.toml", "setup.py", "setup.cfg", "pytest.ini", "tox.ini")
    has_py_tests = (wd / "tests").is_dir() or any(wd.glob("test_*.py")) or any(wd.glob("*/test_*.py"))
    if any((wd / m).exists() for m in py_markers) and has_py_tests:
        if (wd / "uv.lock").exists() and _has_tool("uv"):
            return "uv run pytest -q"
        return f"{procs.PYTHON_CMD} -m pytest -q"
    pkg = wd / "package.json"
    if pkg.is_file():
        try:
            script = (json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {}).get("test", "")
        except (OSError, ValueError):
            script = ""
        if script and "no test specified" not in script:
            return "npm test --silent"
    if (wd / "Cargo.toml").is_file():
        return "cargo test --quiet"
    if (wd / "go.mod").is_file():
        return "go test ./..."
    mk = wd / "Makefile"
    if mk.is_file():
        try:
            if re.search(r"^test\s*:", mk.read_text(encoding="utf-8", errors="replace"), re.MULTILINE):
                return "make test"
        except OSError:
            pass
    if has_py_tests:
        return f"{procs.PYTHON_CMD} -m pytest -q"
    return None


def run_tests(workdir: Path, command: str, source: str, timeout_sec: int,
              drop_env: Collection[str] = ()) -> TestResult:
    """drop_env: 상속 환경에서 뺄 변수 이름 (에이전트가 쓴 코드를 돌리므로 비밀 변수를 넘기지 않는다)."""
    r = run_process(procs.shell_argv(command), cwd=workdir, timeout_sec=timeout_sec,
                    env={"CI": "1", "PYTHONDONTWRITEBYTECODE": "1"}, drop_env=drop_env)
    # 도구의 안내(uv 의 설치 메시지 등)는 보통 stderr 로 나오므로 앞에 두고, 결과 요약은 stdout 끝에서 찾는다
    out = ((r.stderr.strip() + "\n") if r.stderr.strip() else "") + r.stdout.strip()
    if r.timed_out:
        status = "timeout"
    elif r.exit_code == 0:
        status = "passed"
    elif (r.exit_code in NOT_RUNNABLE_EXITS or (r.exit_code == PYTEST_NO_TESTS and "pytest" in command)
          or procs.shell_command_missing(command)):
        status = "error"
    else:
        status = "failed"
    lines = [ln.strip() for ln in (r.stdout.splitlines() or r.stderr.splitlines()) if ln.strip()]
    if not lines:
        lines = [ln.strip() for ln in r.stderr.splitlines() if ln.strip()]
    summary = lines[-1][:200] if lines else ""
    return TestResult(command=command, source=source, status=status, exit_code=r.exit_code,
                      duration_sec=round(r.duration_sec, 1), summary=summary, output_tail=out[-OUTPUT_TAIL:])


STATUS_KO = {"passed": "통과", "failed": "실패", "error": "실행 불가", "timeout": "시간 초과"}


def describe_for_prompt(result: TestResult | None) -> str:
    if result is None:
        return "(테스트 명령이 없어 duet 가 테스트를 돌리지 않았다)"
    head = f"명령: {result.command} ({result.source})\n결과: {STATUS_KO[result.status]} (exit {result.exit_code}, {result.duration_sec}초)"
    if result.status == "error":
        head += "\n(명령을 실행할 수 없었다. 코드 결함이 아니라 환경 문제일 수 있다.)"
    return f"{head}\n출력 끝부분:\n```\n{result.output_tail or '(출력 없음)'}\n```"
