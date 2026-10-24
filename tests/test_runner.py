import sys
from pathlib import Path

import pytest

from tenure.runner import TIMEOUT_EXIT_CODE, ExecutableNotFound, run_process


def test_run_captures_output(tmp_path: Path):
    r = run_process([sys.executable, "-c", "import sys; print('out'); sys.stderr.write('err')"], cwd=tmp_path)
    assert r.ok
    assert r.exit_code == 0
    assert r.stdout.strip() == "out"
    assert r.stderr == "err"
    assert r.duration_sec >= 0


def test_nonzero_exit(tmp_path: Path):
    r = run_process([sys.executable, "-c", "raise SystemExit(3)"], cwd=tmp_path)
    assert not r.ok and r.exit_code == 3


def test_stdin_text(tmp_path: Path):
    r = run_process([sys.executable, "-c", "import sys; print(sys.stdin.read())"], cwd=tmp_path, stdin_text="hello")
    assert r.stdout.strip() == "hello"


def test_stdin_devnull_when_absent(tmp_path: Path):
    r = run_process([sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"], cwd=tmp_path)
    assert r.stdout.strip() == "''"


def test_cwd_and_env(tmp_path: Path):
    r = run_process(
        [sys.executable, "-c", "import os; print(os.getcwd()); print(os.environ['TENURE_X'])"],
        cwd=tmp_path, env={"TENURE_X": "1"},
    )
    lines = r.stdout.splitlines()
    assert Path(lines[0]).resolve() == tmp_path.resolve()
    assert lines[1] == "1"


def test_timeout(tmp_path: Path):
    r = run_process([sys.executable, "-c", "import time; time.sleep(30)"], cwd=tmp_path, timeout_sec=1)
    assert r.timed_out
    assert r.exit_code == TIMEOUT_EXIT_CODE
    assert not r.ok
    assert r.duration_sec < 10


def test_missing_executable(tmp_path: Path):
    with pytest.raises(ExecutableNotFound) as e:
        run_process(["definitely-not-a-real-binary-xyz"], cwd=tmp_path)
    assert "definitely-not-a-real-binary-xyz" in str(e.value)
