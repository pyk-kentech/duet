"""Phase 테스트용 헬퍼."""

from __future__ import annotations

import sys
from pathlib import Path

from duet.agents.mock import MockAdapter
from duet.config import load_config
from duet.phases.common import PhaseContext
from duet.state import RunState, create_run_dir
from duet.transcript import Transcript


def make_ctx(workdir: Path, agents: dict[str, MockAdapter] | None = None,
             overrides: dict | None = None, task: str = "메모 CLI",
             run_id: str = "20261014-000001", state: RunState | None = None) -> PhaseContext:
    workdir.mkdir(parents=True, exist_ok=True)
    cfg = load_config(workdir, {"timeout_sec": 5, **(overrides or {})})
    if agents is None:
        agents = {n: MockAdapter(label=n) for n in ("claude", "codex")}
    run_dir = workdir / ".duet" / "runs" / run_id
    if state is None:
        if not run_dir.exists():
            run_dir = create_run_dir(workdir, run_id)
        state = RunState(run_id=run_id, task=task)
    logs: list[str] = []
    ctx = PhaseContext(task=task, workdir=workdir, cfg=cfg, agents=agents, state=state,
                       transcript=Transcript(run_dir), run_dir=run_dir, log=logs.append)
    ctx.logs = logs  # type: ignore[attr-defined]
    return ctx


def file_names(run_dir: Path) -> list[str]:
    return sorted(p.name for p in run_dir.iterdir() if p.suffix == ".md")


def py_cmd(code: str) -> str:
    """OS 셸(sh·cmd.exe)에서 똑같이 도는 파이썬 한 줄 명령 (DESIGN.md 27.7).

    code 에는 큰따옴표·$·% 를 쓰지 마라(셸이 해석한다).
    """
    assert '"' not in code and "$" not in code and "%" not in code, code
    return f'"{sys.executable}" -c "{code}"'


PASS_CMD = py_cmd("pass")
FAIL_CMD = py_cmd("import sys; sys.exit(1)")


def echo_exit(text: str, code: int = 1, stderr: bool = False) -> str:
    """text 를 출력하고 code 로 끝나는 셸 명령."""
    stream = "sys.stderr" if stderr else "sys.stdout"
    return py_cmd(f"import sys; print({text!r}, file={stream}); sys.exit({code})")

