"""Codex CLI 어댑터.

호출 형태(codex-cli 0.16x 기준, `codex exec --help`로 확인):
  codex exec --skip-git-repo-check -C <cwd> [모드별 플래그] -o <last_msg_file> <prompt>
- 결과: `-o/--output-last-message` 파일 내용. 비어 있으면 stdout 전체.
- 긴 프롬프트: 프롬프트 자리에 `-`를 주면 stdin에서 읽는다.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from duet.agents.base import (
    AgentNotAvailable,
    AgentRequest,
    AgentResult,
    Mode,
    compile_rate_limit_patterns,
    detect_rate_limit,
)
from duet.config import AgentConfig, Config
from duet.runner import ExecutableNotFound, run_process

STDIN_MARKER = "-"


class CodexAdapter:
    name = "codex"

    def __init__(self, cfg: Config, agent_cfg: AgentConfig | None = None):
        self.cfg = cfg
        self.agent_cfg = agent_cfg or cfg.codex
        self._rl_patterns: list[re.Pattern[str]] = compile_rate_limit_patterns(cfg.rate_limit_patterns)

    # ---------------------------------------------------------------- check
    def check(self) -> None:
        try:
            r = run_process([self.agent_cfg.bin, "--version"], cwd=Path.cwd(), timeout_sec=30)
        except ExecutableNotFound as e:
            raise AgentNotAvailable(
                f"Codex CLI를 찾을 수 없습니다: {e.executable}\n"
                "  설치: npm install -g @openai/codex\n"
                "  로그인: codex login\n"
                "  경로가 다르면 duet.toml 의 [codex] bin 으로 지정하세요."
            ) from e
        if not r.ok:
            raise AgentNotAvailable(
                f"`{self.agent_cfg.bin} --version` 실행 실패 (exit {r.exit_code}): {r.stderr.strip()[-500:]}"
            )

    # ---------------------------------------------------------------- build
    def build_command(
        self, req: AgentRequest, last_message_path: Path
    ) -> tuple[list[str], str | None]:
        mode_args = self.agent_cfg.read_args if req.mode is Mode.READ else self.agent_cfg.write_args
        cmd = [
            self.agent_cfg.bin,
            *self.agent_cfg.base_args,
            "-C", str(req.cwd),
            *mode_args,
            "--output-last-message", str(last_message_path),
        ]
        if len(req.prompt) > self.cfg.prompt_arg_max_chars:
            return [*cmd, STDIN_MARKER], req.prompt
        return [*cmd, req.prompt], None

    # ---------------------------------------------------------------- ask
    def ask(self, req: AgentRequest) -> AgentResult:
        fd, tmp = tempfile.mkstemp(prefix="duet-codex-", suffix=".md")
        os.close(fd)
        last_message_path = Path(tmp)
        try:
            cmd, stdin_text = self.build_command(req, last_message_path)
            r = run_process(cmd, cwd=req.cwd, timeout_sec=req.timeout_sec, stdin_text=stdin_text)
            text = self.read_last_message(last_message_path)
            if not text:
                text = r.stdout.strip()
        finally:
            last_message_path.unlink(missing_ok=True)
        return AgentResult(
            text=text,
            raw_stdout=r.stdout,
            raw_stderr=r.stderr,
            exit_code=r.exit_code,
            duration_sec=r.duration_sec,
            rate_limited=detect_rate_limit((r.stderr, r.stdout, text), self._rl_patterns),
            timed_out=r.timed_out,
            command=cmd,
        )

    @staticmethod
    def read_last_message(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return ""
