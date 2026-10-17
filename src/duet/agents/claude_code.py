"""Claude Code CLI 어댑터.

호출 형태(Claude Code 2.1.x 기준, `claude --help`로 확인):
  claude -p --output-format stream-json --verbose [모드별 플래그] -- <prompt>
- 스트림의 마지막 `result` 이벤트는 예전 `--output-format json` 출력과 같은 필드다. 같은 스트림의
  `rate_limit_event` 에 구독 사용률(5시간·7일)이 들어 있다 (DESIGN.md 28.6). json 출력 설정도 그대로 읽는다.
- `--` 는 필수: `--allowedTools <tools...>` 가 공백 구분 가변 인자라 뒤따르는 프롬프트를 삼킨다.
- 결과: stdout JSON의 `result` 필드. JSON이 아니면 stdout 전체.
- 긴 프롬프트: 위치 인자를 생략하면 stdin을 프롬프트로 읽는다.
"""

from __future__ import annotations

import json
import re
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
    prompt_via_stdin,
    should_fall_back,
)
from duet.config import AgentConfig, Config
from duet.runner import ExecutableNotFound, env_drops, run_process
from duet.usage import claude_call_usage


class ClaudeCodeAdapter:
    name = "claude"

    def __init__(self, cfg: Config, agent_cfg: AgentConfig | None = None):
        self.cfg = cfg
        self.agent_cfg = agent_cfg or cfg.claude
        self._rl_patterns: list[re.Pattern[str]] = compile_rate_limit_patterns(cfg.rate_limit_patterns)

    # ---------------------------------------------------------------- check
    def check(self) -> None:
        try:
            r = run_process([self.agent_cfg.bin, "--version"], cwd=Path.cwd(), timeout_sec=30)
        except ExecutableNotFound as e:
            raise AgentNotAvailable(
                f"Claude Code CLI를 찾을 수 없습니다: {e.executable}\n"
                "  설치: npm install -g @anthropic-ai/claude-code\n"
                "  로그인: claude (대화형으로 한 번 실행해 로그인)\n"
                "  경로가 다르면 duet.toml 의 [claude] bin 으로 지정하세요."
            ) from e
        if not r.ok:
            raise AgentNotAvailable(
                f"`{self.agent_cfg.bin} --version` 실행 실패 (exit {r.exit_code}): {r.stderr.strip()[-500:]}"
            )

    # ---------------------------------------------------------------- build
    def build_command(self, req: AgentRequest) -> tuple[list[str], str | None]:
        """(명령어, stdin 텍스트)를 돌려준다. 프롬프트가 길면 stdin으로 넘긴다."""
        mode_args = self.agent_cfg.read_args if req.mode is Mode.READ else self.agent_cfg.write_args
        effort = req.effort if req.effort is not None else self.agent_cfg.effort_for(req.step, req.round)
        base = (self.agent_cfg.resume_args or self.agent_cfg.base_args) if req.resume_session else self.agent_cfg.base_args
        if req.resume_session and self.agent_cfg.resume_read_args and req.mode is Mode.READ:
            mode_args = self.agent_cfg.resume_read_args
        cmd = [self.agent_cfg.bin, *base, *self.model_args(effort, self.agent_cfg.model_for(req.step, req.round)), *mode_args]
        if self.cfg.claude_sandbox and req.mode is Mode.WRITE and self.agent_cfg.sandbox_settings:
            cmd += ["--settings", self.agent_cfg.sandbox_settings]   # OS 샌드박스 (DESIGN.md 24.3)
        if req.output_schema is not None:
            cmd += ["--json-schema", json.dumps(req.output_schema, ensure_ascii=False)]
        if req.resume_session:
            cmd += ["--resume", req.resume_session]
        if prompt_via_stdin(req.prompt, self.cfg.prompt_arg_max_bytes, self.agent_cfg.bin):
            return cmd, req.prompt
        # `--allowedTools <tools...>` 같은 가변 인자 옵션이 프롬프트를 삼키지 않도록 옵션 종료자를 넣는다
        return [*cmd, "--", req.prompt], None

    def model_args(self, effort: str | None = None, model: str | None = None) -> list[str]:
        """effort·model 이 None 이면 단계 구분 없는 기본값(agent_cfg.effort·model)."""
        effort = self.agent_cfg.effort if effort is None else effort
        model = self.agent_cfg.model if model is None else model
        args: list[str] = []
        if model:
            args += ["--model", model]
        if effort:
            args += ["--effort", effort]
        return args

    # ---------------------------------------------------------------- ask
    def ask(self, req: AgentRequest) -> AgentResult:
        result = self._ask_once(req)
        if should_fall_back(req, result):
            result = self._ask_once(fresh_request(req))
        return result

    def _ask_once(self, req: AgentRequest) -> AgentResult:
        cmd, stdin_text = self.build_command(req)
        r = run_process(cmd, cwd=req.cwd, timeout_sec=req.timeout_sec, stdin_text=stdin_text,
                        drop_env=env_drops(self.cfg.env_strip, self.cfg.env_keep))
        text, is_error = self.parse_output_full(r.stdout)
        data, rate_info = parse_stream(r.stdout)
        usage = claude_call_usage(data) if isinstance(data, dict) else None
        limits = claude_rate_limits(rate_info)
        if limits:
            usage = {**(usage or {}), "rate_limits": limits}
            save_claude_limits(limits)
        session_id = data.get("session_id") if isinstance(data, dict) and isinstance(data.get("session_id"), str) else None
        structured = None
        if req.output_schema is not None:
            so = data.get("structured_output") if isinstance(data, dict) else None
            structured = so if isinstance(so, dict) else parse_structured(text)
        effort = req.effort if req.effort is not None else self.agent_cfg.effort_for(req.step, req.round)
        if usage is not None and effort:
            usage["effort"] = effort
        exit_code = r.exit_code
        if is_error and exit_code == 0:
            exit_code = 1  # JSON 이 is_error 를 알리면 exit 0 이어도 실패로 본다
        return AgentResult(
            text=text,
            raw_stdout=r.stdout,
            raw_stderr=r.stderr,
            exit_code=exit_code,
            duration_sec=r.duration_sec,
            rate_limited=classify_rate_limit(
                failed=exit_code != 0, text=text,
                diagnostics=(r.stderr, r.stdout), patterns=self._rl_patterns,
            ),
            timed_out=r.timed_out,
            command=cmd,
            usage=usage,
            structured=structured,
            session_id=session_id or req.resume_session,
            resumed=bool(req.resume_session),
        )

    @staticmethod
    def parse_output(stdout: str) -> str:
        return ClaudeCodeAdapter.parse_output_full(stdout)[0]

    @staticmethod
    def parse_output_full(stdout: str) -> tuple[str, bool]:
        """(본문, is_error). JSON 이 아니면 stdout 전체와 False. 스트림이면 마지막 result 이벤트."""
        s = stdout.strip()
        if not s:
            return "", False
        data, _ = parse_stream(s)
        if data is None:
            return s, False
        if isinstance(data, dict):
            is_error = bool(data.get("is_error", False))
            result = data.get("result")
            if isinstance(result, str):
                return result.strip(), is_error
            return s, is_error
        return s, False


def parse_stream(stdout: str) -> tuple[dict | None, dict | None]:
    """(result 이벤트 또는 json 출력, 마지막 rate_limit_event 의 rate_limit_info). 못 읽으면 (None, None)."""
    s = stdout.strip()
    if not s:
        return None, None
    try:
        whole = json.loads(s)                    # --output-format json (한 덩어리)
        if isinstance(whole, dict):
            return whole, None
    except ValueError:
        pass
    result, rate = None, None
    for line in s.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "result":
            result = ev
        elif ev.get("type") == "rate_limit_event" and isinstance(ev.get("rate_limit_info"), dict):
            rate = ev["rate_limit_info"]
    return result, rate


def claude_rate_limits(info: dict | None) -> dict | None:
    """rate_limit_info → {five_hour: {used_percent, resets_at}, seven_day: {...}, status, resets_at}.

    Codex 의 rate_limits 요약(usage.summarize_rate_limits)과 같은 used_percent·resets_at 이름을 쓴다.
    """
    if not isinstance(info, dict):
        return None
    out: dict = {}
    windows = info.get("unifiedWindows")
    if isinstance(windows, dict):
        for name, w in windows.items():
            if isinstance(w, dict) and isinstance(w.get("utilization"), (int, float)):
                out[name] = {"used_percent": round(float(w["utilization"]) * 100, 1), "resets_at": w.get("resetsAt")}
    if info.get("status"):
        out["status"] = info["status"]
    if info.get("resetsAt"):
        out["resets_at"] = info["resetsAt"]
    if info.get("rateLimitType"):
        out["type"] = info["rateLimitType"]
    return out or None


def save_claude_limits(limits: dict) -> None:
    """최신 Claude 사용률을 $DUET_HOME/claude_limits.json 에 (사용량 화면용, DESIGN.md 28.6). 실패해도 무시."""
    import datetime as dt

    from duet.registry import duet_home

    try:
        path = duet_home() / CLAUDE_LIMITS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"as_of": dt.datetime.now().isoformat(timespec="seconds"), "limits": limits},
                                  ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def load_claude_limits() -> dict | None:
    from duet.registry import duet_home

    try:
        return json.loads((duet_home() / CLAUDE_LIMITS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


CLAUDE_LIMITS_FILE = "claude_limits.json"

