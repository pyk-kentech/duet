"""M21: 어디서나 실행 — Windows·Linux·SSH (DESIGN.md 27장)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import duet.ui.server as srv_mod
from duet import doctor, limits, procs, stopflag
from duet.agents.base import prompt_via_stdin
from duet.doctor import ACTIONS
from duet.lock import RunLock
from duet.remote import Remote
from duet.runner import pid_alive, run_process
from duet.testing import run_tests
from duet.workspace import Workspace
from tests.helpers import py_cmd

WIN = os.name == "nt"
SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)"]


def wait_until(pred, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.05)
    return pred()


# ====================================================================== 생존 확인·트리 종료 (27.2)
def test_pid_alive_does_not_kill():
    """Windows 에서 os.kill(pid, 0) 은 그 프로세스를 죽인다. 생존 확인이 프로세스를 건드리면 안 된다."""
    p = subprocess.Popen(SLEEPER)
    try:
        for _ in range(5):
            assert pid_alive(p.pid)
        time.sleep(0.3)
        assert p.poll() is None and pid_alive(p.pid)
    finally:
        p.kill()
        p.wait()
    assert wait_until(lambda: not pid_alive(p.pid))
    assert pid_alive(os.getpid()) and not pid_alive(0) and not pid_alive(-5)


def test_kill_tree_kills_grandchildren(tmp_path: Path):
    marker = tmp_path / "grandchild.pid"
    code = ("import subprocess, sys, time, pathlib; "
            f"g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            f"pathlib.Path({str(marker)!r}).write_text(str(g.pid)); time.sleep(60)")
    p = subprocess.Popen([sys.executable, "-c", code], **procs.child_kwargs())
    assert wait_until(lambda: marker.exists() and marker.read_text().strip())
    grand = int(marker.read_text())
    assert pid_alive(grand)
    procs.kill_tree(p, grace=1.0)
    assert p.poll() is not None
    assert wait_until(lambda: not pid_alive(grand)), "손자 프로세스가 남았다"


# ====================================================================== 중지 요청 파일 (27.3)
def test_stop_request_interrupts_running_call(tmp_path: Path):
    stopflag.watch(tmp_path)
    try:
        assert stopflag.active() and not stopflag.requested()
        started = time.monotonic()
        import threading
        threading.Timer(0.8, lambda: stopflag.request(tmp_path)).start()
        with pytest.raises(KeyboardInterrupt):
            run_process(SLEEPER, tmp_path, timeout_sec=60)
        assert time.monotonic() - started < 10
    finally:
        stopflag.unwatch()
    assert not stopflag.active() and not stopflag.stop_path(tmp_path).exists()


def test_stop_request_ignored_when_not_watching(tmp_path: Path):
    stopflag.request(tmp_path)
    r = run_process([sys.executable, "-c", "print('ok')"], tmp_path, timeout_sec=30)
    assert r.ok and r.stdout.strip() == "ok"


def test_limit_sleep_stops_on_request(tmp_path: Path):
    stopflag.watch(tmp_path)
    try:
        stopflag.request(tmp_path)
        with pytest.raises(KeyboardInterrupt):
            limits.sleep(30)
    finally:
        stopflag.unwatch()


def test_run_lock_watches_and_clears_old_request(tmp_path: Path):
    stopflag.request(tmp_path)                      # 예전 실행이 남긴 요청
    with RunLock(tmp_path, "t"):
        assert stopflag.active() and not stopflag.requested()
        stopflag.request(tmp_path)
        assert stopflag.requested()
    assert not stopflag.active() and not stopflag.stop_path(tmp_path).exists()


# ====================================================================== 실행 파일·셸 (27.4)
def test_shell_argv_forms(monkeypatch):
    monkeypatch.setattr(procs, "IS_WINDOWS", False)
    assert procs.shell_argv("echo hi") == ["sh", "-c", "echo hi"]
    monkeypatch.setattr(procs, "IS_WINDOWS", True)
    monkeypatch.setenv("COMSPEC", r"C:\Windows\system32\cmd.exe")
    assert procs.shell_argv('"py.exe" -c "x"') == r'C:\Windows\system32\cmd.exe /d /s /c ""py.exe" -c "x""'


def test_shell_command_with_quotes_runs(tmp_path: Path):
    """인터프리터 경로에 공백이 있어도(따옴표) 두 OS 의 셸에서 돈다."""
    r = run_tests(tmp_path, py_cmd("import sys; print('quoted ok'); sys.exit(0)"), "t", 30)
    assert r.status == "passed" and "quoted ok" in r.output_tail


def test_missing_command_is_error_not_failure(tmp_path: Path):
    assert run_tests(tmp_path, "no-such-test-runner-xyz", "t", 30).status == "error"


def test_prompt_via_stdin_rules(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(procs, "IS_WINDOWS", False)
    assert not prompt_via_stdin("x" * 50_000, 100_000, "claude")
    assert prompt_via_stdin("x" * 100_001, 100_000, "claude")
    monkeypatch.setattr(procs, "IS_WINDOWS", True)
    monkeypatch.setattr(procs, "is_batch", lambda exe, path=None: exe.endswith(".cmd"))
    assert prompt_via_stdin("x" * 30_000, 100_000, "claude.exe")          # Windows 명령줄 한도
    assert not prompt_via_stdin("short", 100_000, "claude.exe")
    assert prompt_via_stdin("short", 100_000, "codex.cmd")                # 배치 파일은 항상 stdin


@pytest.mark.skipif(not WIN, reason="Windows 전용")
def test_windows_resolves_batch_and_python_script(tmp_path: Path):
    script = tmp_path / "fakecli"
    script.write_text("#!/usr/bin/env python3\nimport sys\nprint('args:' + ' '.join(sys.argv[1:]))\n", encoding="utf-8")
    assert procs.resolve_argv([str(script), "a"])[:2] == [sys.executable, str(script)]
    r = run_process([str(script), "x", "y"], tmp_path, timeout_sec=30)
    assert r.ok and r.stdout.strip() == "args:x y"
    bat = tmp_path / "tool.cmd"
    bat.write_bytes(f'@"{sys.executable}" "{script}" %*\r\n'.encode())
    assert procs.is_batch(str(bat)) and not procs.is_batch(sys.executable)
    r = run_process(["tool", "z"], tmp_path, timeout_sec=30, env={"PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]})
    assert r.ok and r.stdout.strip() == "args:z"


def test_child_python_uses_utf8(tmp_path: Path):
    r = run_process([sys.executable, "-c", "import sys; d = sys.stdin.read(); print(len(d), d[:2])"], tmp_path,
                    stdin_text="한글✅" * 10, timeout_sec=30)
    assert r.ok and r.stdout.strip() == "30 한글"


def test_new_repo_keeps_bytes(tmp_path: Path):
    ws = Workspace(tmp_path / "r")
    ws.ensure_repo()
    assert ws.git("config", "core.autocrlf").strip() == "false"


# ====================================================================== 설치·로그인 동작 (27.5)
def test_actions_per_os(monkeypatch):
    monkeypatch.setattr(doctor, "IS_WINDOWS", True)
    assert "install.ps1" in ACTIONS["install_claude"].local_command()
    assert "npm install -g @openai/codex" in ACTIONS["install_codex"].local_command()
    assert ACTIONS["install_curl"].local_command() is None and not ACTIONS["install_curl"].available_locally()
    assert ACTIONS["login_claude"].local_command() == "claude auth login"
    monkeypatch.setattr(doctor, "IS_WINDOWS", False)
    assert ACTIONS["install_claude"].local_command() == ACTIONS["install_claude"].shell


def test_local_action_argv(monkeypatch):
    monkeypatch.setattr(doctor, "IS_WINDOWS", True)
    monkeypatch.setattr(procs, "IS_WINDOWS", True)
    argv, mode = srv_mod.local_action_argv(ACTIONS["login_claude"])
    assert mode == "console" and argv[0] == "powershell" and "-NoExit" in argv and argv[-1] == "claude auth login"
    argv, mode = srv_mod.local_action_argv(ACTIONS["install_uv"])
    assert mode == "pipe" and "-NoExit" not in argv and argv[-1].startswith("irm https://astral.sh/uv/install.ps1")
    monkeypatch.setattr(doctor, "IS_WINDOWS", False)
    monkeypatch.setattr(procs, "IS_WINDOWS", False)
    argv, mode = srv_mod.local_action_argv(ACTIONS["login_claude"])
    assert mode == "pty" and argv[:2] == ["sh", "-c"] and argv[2].endswith("claude auth login")


def test_term_job_pipe_mode():
    from duet.ui.terminal import TermJob
    script = "import sys; print('ask?', flush=True); print('got:' + sys.stdin.readline().strip(), flush=True)"
    job = TermJob(id="p", title="pipe", argv=[sys.executable, "-c", script], mode="pipe").start()
    assert wait_until(lambda: "ask?" in job.snapshot()["text"])
    job.write("Q-1")
    assert wait_until(lambda: not job.running)
    snap = job.snapshot()
    assert snap["mode"] == "pipe" and snap["returncode"] == 0 and "got:Q-1" in snap["text"]


# ====================================================================== SSH (27.6)
def test_ssh_argv_without_multiplexing_on_windows(monkeypatch):
    r = Remote({"id": "m", "ssh": "user@host", "port": 2222})
    monkeypatch.setattr(procs, "IS_WINDOWS", True)
    argv = r.ssh_argv()
    assert not any(a.startswith("Control") for a in argv) and argv[-2:] == ["--", "user@host"] and "2222" in argv
    monkeypatch.setattr(procs, "IS_WINDOWS", False)
    assert any(a.startswith("ControlMaster") for a in r.ssh_argv())
