"""Codex CLI 어댑터.

호출 형태(codex-cli 0.16x 기준, `codex exec --help`로 확인):
  codex exec --skip-git-repo-check -C <cwd> [모드별 플래그] -o <last_msg_file> -- <prompt>
- 결과: `-o/--output-last-message` 파일 내용. 비어 있으면 stdout 전체.
- 긴 프롬프트: 프롬프트 자리에 `-`를 주면 stdin에서 읽는다.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path

from duet.agents.base import (
    AgentNotAvailable,
    AgentRequest,
    AgentResult,
    Mode,
    classify_rate_limit,
    compile_rate_limit_patterns,
    fresh_request,
    parse_structured,
    should_fall_back,
)
from duet.config import AgentConfig, Config
from duet.runner import ExecutableNotFound, env_drops, run_process
from duet.usage import codex_call_usage

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
        self, req: AgentRequest, last_message_path: Path, schema_path: Path | None = None
    ) -> tuple[list[str], str | None]:
        if self._resumes(req):
            # codex exec resume [OPTIONS] [SESSION_ID] [PROMPT] — --sandbox·-C 가 없다 (DESIGN.md 21.3)
            cmd = [self.agent_cfg.bin, *self.agent_cfg.resume_args,
                   *self.model_args(self._effort(req)),
                   *(self.agent_cfg.resume_read_args or self.agent_cfg.read_args)]
            if schema_path is not None:
                cmd += ["--output-schema", str(schema_path)]
            cmd += ["--output-last-message", str(last_message_path), "--", req.resume_session]  # type: ignore[list-item]
            if len(req.prompt.encode("utf-8")) > self.cfg.prompt_arg_max_bytes:
                return [*cmd, STDIN_MARKER], req.prompt
            return [*cmd, req.prompt], None
        mode_args = self.agent_cfg.read_args if req.mode is Mode.READ else self.agent_cfg.write_args
        cmd = [
            self.agent_cfg.bin,
            *self.agent_cfg.base_args,
            *self.model_args(self._effort(req)),
            "-C", str(req.cwd),
            *mode_args,
            *(["--output-schema", str(schema_path)] if schema_path is not None else []),
            "--output-last-message", str(last_message_path),
        ]
        if len(req.prompt.encode("utf-8")) > self.cfg.prompt_arg_max_bytes:
            return [*cmd, STDIN_MARKER], req.prompt
        # '-' 로 시작하는 프롬프트가 옵션으로 읽히지 않게 (codex-cli 0.162.1 에서 `--` 동작 확인)
        return [*cmd, "--", req.prompt], None

    def model_args(self, effort: str | None = None) -> list[str]:
        """effort 가 None 이면 단계 구분 없는 기본 강도(agent_cfg.effort)."""
        effort = self.agent_cfg.effort if effort is None else effort
        args: list[str] = []
        if self.agent_cfg.model:
            args += ["-m", self.agent_cfg.model]
        if effort:
            # ~/.codex/config.toml 의 model_reasoning_effort 를 이 호출에서만 덮어쓴다
            args += ["-c", f'model_reasoning_effort="{effort}"']
        return args

    def _effort(self, req: AgentRequest) -> str:
        return req.effort if req.effort is not None else self.agent_cfg.effort_for(req.step, req.round)

    def _resumes(self, req: AgentRequest) -> bool:
        """읽기 모드에서만 이어간다 (resume 에 쓰기용 샌드박스 옵션을 따로 두지 않았다)."""
        return bool(req.resume_session) and req.mode is Mode.READ and bool(self.agent_cfg.resume_args)

    # ---------------------------------------------------------------- ask
    def ask(self, req: AgentRequest) -> AgentResult:
        result = self._ask_once(req)
        if should_fall_back(req, result):
            result = self._ask_once(fresh_request(req))
        return result

    def _ask_once(self, req: AgentRequest) -> AgentResult:
        started = time.time()
        resumed = self._resumes(req)
        fd, tmp = tempfile.mkstemp(prefix="duet-codex-", suffix=".md")
        os.close(fd)
        last_message_path = Path(tmp)
        schema_path = None
        if req.output_schema is not None:
            fd, stmp = tempfile.mkstemp(prefix="duet-codex-schema-", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(req.output_schema, f, ensure_ascii=False)
            schema_path = Path(stmp)
        try:
            cmd, stdin_text = self.build_command(req, last_message_path, schema_path)
            r = run_process(cmd, cwd=req.cwd, timeout_sec=req.timeout_sec, stdin_text=stdin_text,
                            drop_env=env_drops(self.cfg.env_strip, self.cfg.env_keep))
            text = self.read_last_message(last_message_path)
            if not text:
                text = r.stdout.strip()
        finally:
            last_message_path.unlink(missing_ok=True)
            if schema_path is not None:
                schema_path.unlink(missing_ok=True)
        try:
            usage = codex_call_usage(req.cwd, started, session_id=req.resume_session if resumed else None)
        except Exception:  # noqa: BLE001 - 사용량은 부가 정보, 실패해도 호출 결과는 살린다
            usage = None
        session_id = (usage or {}).get("session_id") or (req.resume_session if resumed else None)
        structured = parse_structured(text) if req.output_schema is not None else None
        return AgentResult(
            text=text,
            raw_stdout=r.stdout,
            raw_stderr=r.stderr,
            exit_code=r.exit_code,
            duration_sec=r.duration_sec,
            rate_limited=classify_rate_limit(
                failed=r.exit_code != 0, text=text,
                diagnostics=(r.stderr, r.stdout), patterns=self._rl_patterns,
            ),
            timed_out=r.timed_out,
            command=cmd,
            usage=usage,
            structured=structured,
            session_id=session_id,
            resumed=resumed,
        )

    @staticmethod
    def read_last_message(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return ""
