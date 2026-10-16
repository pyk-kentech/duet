"""설정: 기본값 + <workdir>/duet.toml + CLI 인자 덮어쓰기.

우선순위: CLI 인자 > duet.toml > 기본값
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Mapping

AGENT_NAMES = ("claude", "codex")

MAX_DEBATE_ROUNDS = 5
SEVERITIES = ("P1", "P2", "P3")
MAX_REVIEW_ROUNDS = 10

# 한도 도달 감지용 정규식(대소문자 무시). stdout/stderr/응답 본문에 적용.
DEFAULT_RATE_LIMIT_PATTERNS = [
    r"rate[ _-]?limit",
    r"usage[ _-]?limit",
    r"too many requests",
    r"quota (?:has been )?exceeded",
    r"(?:hit|reached) (?:your|the) (?:usage |weekly |daily |session )?limit",
    r"limit reached",
    r"\b429\b",
]


DEFAULT_DIFF_EXCLUDES = [
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "npm-shrinkwrap.json",
    "uv.lock", "poetry.lock", "Pipfile.lock", "pdm.lock",
    "Cargo.lock", "go.sum", "composer.lock", "Gemfile.lock", "mix.lock", "pubspec.lock",
]

# 이름이 바뀐 설정 키 (예전 duet.toml 호환)
RENAMED_KEYS = {"prompt_arg_max_chars": "prompt_arg_max_bytes"}


# 워크플로 템플릿 이름 (DESIGN.md 19.4). "@경로.toml" 로 파일을 직접 줄 수도 있다
WORKFLOW_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
CLASSIC_WORKFLOW = "classic"

_TOKEN_RE = re.compile(r"^[A-Za-z0-9._:\[\]/-]{0,80}$")
EFFORT_SUGGESTIONS = {
    "claude": ["low", "medium", "high", "xhigh", "max"],
    "codex": ["minimal", "low", "medium", "high", "xhigh", "max"],
}
# step_effort 의 키. "rereview" 는 2라운드부터의 리뷰 (DESIGN.md 18.1)
EFFORT_STEPS = ("propose", "critique", "synthesize", "implement", "fix", "review", "rereview", "arbitrate")

# 에이전트·테스트 자식 프로세스에서 뺄 환경 변수 이름(glob, 대소문자 무시) (DESIGN.md 18.2)
DEFAULT_ENV_STRIP = [
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY",
    "*_API_KEY", "*_TOKEN", "*_SECRET", "*_SECRET_*", "*_PASSWORD",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "GOOGLE_APPLICATION_CREDENTIALS", "SSH_AUTH_SOCK",
]
# 패턴에 걸려도 남길 이름. Claude 구독 인증 토큰이라 빼면 로그인이 풀린다.
DEFAULT_ENV_KEEP = ["CLAUDE_CODE_OAUTH_TOKEN"]

CLAUDE_MODEL_SUGGESTIONS = ["fable", "opus", "sonnet", "haiku",
                            "claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]


class ConfigError(Exception):
    """설정 값이 잘못됨."""


@dataclass
class AgentConfig:
    bin: str
    base_args: list[str] = field(default_factory=list)
    read_args: list[str] = field(default_factory=list)
    write_args: list[str] = field(default_factory=list)
    # 리뷰어 세션 이어가기 (DESIGN.md 21.3). 비우면 base_args / read_args 를 그대로 쓴다
    resume_args: list[str] = field(default_factory=list)
    resume_read_args: list[str] = field(default_factory=list)
    model: str = ""     # 비우면 CLI 기본 모델
    effort: str = ""    # 추론 강도. 비우면 CLI 기본값
    # 단계별 추론 강도 {단계: 강도}. 없는 단계는 effort (DESIGN.md 18.1)
    step_effort: dict[str, str] = field(default_factory=dict)
    # claude_sandbox 를 켜면 쓰기 모드에 붙이는 설정 JSON (DESIGN.md 24.3, Claude 만)
    sandbox_settings: str = ""

    def effort_for(self, step: str, round_: int = 0) -> str:
        """이 호출에 쓸 추론 강도. 리뷰는 2라운드부터 "rereview" 키를 본다."""
        key = "rereview" if step == "review" and round_ >= 2 else step
        return self.step_effort.get(key) or self.effort


CLAUDE_SANDBOX_SETTINGS = json.dumps(
    {"sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True, "allowUnsandboxedCommands": False}})


def _default_claude() -> AgentConfig:
    return AgentConfig(
        bin="claude",
        base_args=["-p", "--output-format", "json"],
        read_args=["--allowedTools", "Read,Glob,Grep"],
        write_args=[
            "--permission-mode", "acceptEdits",
            "--allowedTools", "Read,Edit,Write,Glob,Grep,Bash",
        ],
        sandbox_settings=CLAUDE_SANDBOX_SETTINGS,
    )


def _default_codex() -> AgentConfig:
    return AgentConfig(
        bin="codex",
        base_args=["exec", "--skip-git-repo-check"],
        read_args=["--sandbox", "read-only"],
        write_args=["--sandbox", "workspace-write"],
        # codex exec resume 에는 --sandbox·-C 가 없다 → 설정 덮어쓰기로 읽기 전용 유지
        resume_args=["exec", "resume", "--skip-git-repo-check"],
        resume_read_args=["-c", 'sandbox_mode="read-only"'],
        # 추론 출력은 입력보다 요율이 훨씬 높다. 설계 종합과 첫 리뷰만 high (DESIGN.md 18.1)
        effort="medium",
        step_effort={"synthesize": "high", "review": "high", "arbitrate": "high"},
    )


@dataclass
class Config:
    workflow: str = CLASSIC_WORKFLOW   # 워크플로 템플릿 (DESIGN.md 19장)
    implementer: str = "claude"
    reviewer: str = "codex"
    synth: str | None = None  # None이면 reviewer
    debate_rounds: int = 1
    max_review: int = 3
    timeout_sec: int = 1200
    max_diff_chars: int = 60_000
    # 프롬프트가 이 크기(UTF-8 바이트)를 넘으면 인자 대신 stdin으로 전달.
    # Linux 는 인자 하나를 128KiB 로 제한하고 한글은 글자당 3바이트라 '글자 수'로 재면 넘친다.
    prompt_arg_max_bytes: int = 100_000
    # 리뷰 diff 에서 뺄 경로(glob). 잠금 파일은 크고 이름순으로 앞에 와서 실제 코드를 밀어낸다.
    diff_excludes: list[str] = field(default_factory=lambda: list(DEFAULT_DIFF_EXCLUDES))
    # 구현 후 duet 가 직접 돌릴 테스트 명령. "auto" 면 작업 폴더의 duet.toml(test_command) → 자동 감지, "none" 이면 끔
    test_command: str = "auto"
    test_timeout_sec: int = 600
    require_tests_pass: bool = True     # 테스트가 실패하면 리뷰어가 승인해도 승인하지 않음
    block_severity: str = "P2"          # 이 심각도 이상(P1..P2)의 지적이 남아 있으면 반려
    stall_rounds: int = 2               # 막는 지적 수가 N 라운드 연속 최저치를 못 갱신하면 멈춤 (0=끔)
    review_diff: str = "incremental"    # 2라운드부터 지난 리뷰 이후 바뀐 부분만 diff 로 (full: 매번 전체)
    repro_tests: bool = True            # 리뷰어의 <repro> 재현 테스트를 저장·실행
    # 리뷰 비용 (DESIGN.md 21장)
    review_packet: bool = True          # 함수 단위 문맥 diff + 바뀐 함수의 호출부 + 재열람 자제 안내
    review_json: bool = True            # 출력 스키마로 판정을 JSON 으로 받기
    # 2라운드부터 리뷰어 자기 세션 이어가기(reuse). 실측에서 이어간 턴이 캐시를 못 써 한도 기준으로 더 비싸서
    # 기본은 매번 새 세션(fresh) — DESIGN.md 21.3
    review_session: str = "fresh"
    review_session_rounds: int = 3      # 한 세션을 쓰는 최대 라운드 수
    review_gates: bool = True           # JSON 판정의 지적 원장·근거 관문·범위 관문 (DESIGN.md 22장)
    arbiter: bool = True                # 수렴 실패·상한에서 한 번 부르는 분쟁 중재자 (DESIGN.md 23장)
    test_guard: bool = True             # 테스트 변조 감지 → 리뷰어·중재자에게 경고 (DESIGN.md 24.1)
    claude_sandbox: bool = False        # Claude 쓰기 모드에 OS 샌드박스 설정을 붙임 (DESIGN.md 24.3)
    rate_limit_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_RATE_LIMIT_PATTERNS))
    env_strip: list[str] = field(default_factory=lambda: list(DEFAULT_ENV_STRIP))
    env_keep: list[str] = field(default_factory=lambda: list(DEFAULT_ENV_KEEP))
    claude: AgentConfig = field(default_factory=_default_claude)
    codex: AgentConfig = field(default_factory=_default_codex)

    @property
    def synth_name(self) -> str:
        return self.synth or self.reviewer

    def agent(self, name: str) -> AgentConfig:
        if name not in AGENT_NAMES:
            raise ConfigError(f"알 수 없는 에이전트: {name} (가능: {', '.join(AGENT_NAMES)})")
        return getattr(self, name)

    def validate(self) -> None:
        w = self.workflow
        if not isinstance(w, str) or not (WORKFLOW_NAME_RE.match(w) or (w.startswith("@") and 1 < len(w) <= 500)):
            raise ConfigError(f"workflow 값이 잘못되었습니다: {w!r} (템플릿 이름 또는 @파일경로)")
        for key in ("implementer", "reviewer"):
            v = getattr(self, key)
            if v not in AGENT_NAMES:
                raise ConfigError(f"{key} 값이 잘못됨: {v!r} (가능: {', '.join(AGENT_NAMES)})")
        if self.synth is not None and self.synth not in AGENT_NAMES:
            raise ConfigError(f"synth 값이 잘못됨: {self.synth!r} (가능: {', '.join(AGENT_NAMES)})")
        if self.implementer == self.reviewer:
            raise ConfigError("implementer와 reviewer는 서로 달라야 합니다")
        if not (0 <= self.debate_rounds <= MAX_DEBATE_ROUNDS):
            raise ConfigError(f"debate_rounds는 0~{MAX_DEBATE_ROUNDS} 사이여야 합니다: {self.debate_rounds}")
        if not (1 <= self.max_review <= MAX_REVIEW_ROUNDS):
            raise ConfigError(f"max_review는 1~{MAX_REVIEW_ROUNDS} 사이여야 합니다: {self.max_review}")
        if self.timeout_sec <= 0:
            raise ConfigError(f"timeout_sec는 양수여야 합니다: {self.timeout_sec}")
        if self.max_diff_chars <= 0:
            raise ConfigError(f"max_diff_chars는 양수여야 합니다: {self.max_diff_chars}")
        if not (0 < self.prompt_arg_max_bytes <= 120_000):
            raise ConfigError(f"prompt_arg_max_bytes는 1~120000 사이여야 합니다: {self.prompt_arg_max_bytes}")
        if not isinstance(self.diff_excludes, list) or not all(isinstance(x, str) for x in self.diff_excludes):
            raise ConfigError("diff_excludes는 문자열 리스트여야 합니다")
        if not isinstance(self.test_command, str) or len(self.test_command) > 500 or "\n" in self.test_command:
            raise ConfigError("test_command 는 한 줄 명령(500자 이하)이어야 합니다")
        if not isinstance(self.test_timeout_sec, int) or self.test_timeout_sec <= 0:
            raise ConfigError(f"test_timeout_sec는 양수여야 합니다: {self.test_timeout_sec}")
        if not isinstance(self.require_tests_pass, bool):
            raise ConfigError("require_tests_pass 는 true/false 여야 합니다")
        if self.block_severity not in SEVERITIES:
            raise ConfigError(f"block_severity 는 {', '.join(SEVERITIES)} 중 하나여야 합니다: {self.block_severity!r}")
        if self.review_diff not in ("incremental", "full"):
            raise ConfigError(f"review_diff 는 incremental 또는 full 이어야 합니다: {self.review_diff!r}")
        if not isinstance(self.repro_tests, bool):
            raise ConfigError("repro_tests 는 true/false 여야 합니다")
        for key in ("review_packet", "review_json", "review_gates", "arbiter", "test_guard", "claude_sandbox"):
            if not isinstance(getattr(self, key), bool):
                raise ConfigError(f"{key} 는 true/false 여야 합니다")
        if self.review_session not in ("reuse", "fresh"):
            raise ConfigError(f"review_session 은 reuse 또는 fresh 여야 합니다: {self.review_session!r}")
        if (isinstance(self.review_session_rounds, bool) or not isinstance(self.review_session_rounds, int)
                or not 1 <= self.review_session_rounds <= MAX_REVIEW_ROUNDS):
            raise ConfigError(f"review_session_rounds 는 1~{MAX_REVIEW_ROUNDS} 사이여야 합니다: {self.review_session_rounds}")
        if not isinstance(self.stall_rounds, int) or not 0 <= self.stall_rounds <= MAX_REVIEW_ROUNDS:
            raise ConfigError(f"stall_rounds 는 0~{MAX_REVIEW_ROUNDS} 사이여야 합니다: {self.stall_rounds}")
        for key in ("env_strip", "env_keep"):
            v = getattr(self, key)
            if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
                raise ConfigError(f"{key}는 빈 문자열이 없는 문자열 리스트여야 합니다")
        for name in AGENT_NAMES:
            ac = self.agent(name)
            if not ac.bin:
                raise ConfigError(f"[{name}] bin 이 비어 있습니다")
            for key in ("base_args", "read_args", "write_args", "resume_args", "resume_read_args"):
                v = getattr(ac, key)
                if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                    raise ConfigError(f"[{name}] {key}는 문자열 리스트여야 합니다")
            for key in ("model", "effort"):
                v = getattr(ac, key)
                if not isinstance(v, str) or not _TOKEN_RE.match(v):
                    raise ConfigError(f"[{name}] {key} 값이 잘못되었습니다: {v!r} (영문·숫자·.-_:[]/ 만)")
            if not isinstance(ac.sandbox_settings, str):
                raise ConfigError(f"[{name}] sandbox_settings 는 JSON 문자열이어야 합니다")
            if ac.sandbox_settings:
                try:
                    json.loads(ac.sandbox_settings)
                except ValueError as e:
                    raise ConfigError(f"[{name}] sandbox_settings 가 올바른 JSON 이 아닙니다: {e}") from e
            if not isinstance(ac.step_effort, dict):
                raise ConfigError(f"[{name}] step_effort 는 {{단계 = 강도}} 테이블이어야 합니다")
            for step, v in ac.step_effort.items():
                if step not in EFFORT_STEPS:
                    raise ConfigError(f"[{name}] step_effort 의 단계가 잘못되었습니다: {step!r} "
                                      f"(가능: {', '.join(EFFORT_STEPS)})")
                if not isinstance(v, str) or not v or not _TOKEN_RE.match(v):
                    raise ConfigError(f"[{name}] step_effort.{step} 값이 잘못되었습니다: {v!r}")


CONFIG_FILENAME = "duet.toml"

_TOP_LEVEL_KEYS = {
    f.name for f in fields(Config) if f.name not in AGENT_NAMES
}
_AGENT_KEYS = {f.name for f in fields(AgentConfig)}


def load_config(
    workdir: Path | str | None = None,
    overrides: Mapping[str, Any] | None = None,
    *,
    global_defaults: Mapping[str, Any] | None = None,
) -> Config:
    """기본값 → 전역 설정(~/.duet/settings.json 의 defaults) → duet.toml → overrides 순으로 덮어쓴 Config.

    overrides의 None 값은 '지정 안 함'으로 보고 무시한다(CLI 인자 기본값 None 대응).
    overrides 에는 "claude.model" 같은 점 표기 키도 쓸 수 있다.
    """
    cfg = Config()
    if global_defaults is None:
        from duet.settings import global_defaults as _gd  # 순환 import 방지

        global_defaults = _gd()
    if global_defaults:
        cfg = _apply(cfg, global_defaults, source="전역 설정(~/.duet/settings.json)")
    if workdir is not None:
        path = Path(workdir) / CONFIG_FILENAME
        if path.is_file():
            cfg = _apply(cfg, _read_toml(path), source=str(path))
    if overrides:
        cfg = _apply(cfg, _nest({k: v for k, v in overrides.items() if v is not None}), source="CLI 인자")
    cfg.validate()
    return cfg


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path} 파싱 실패: {e}") from e


def _apply(cfg: Config, data: Mapping[str, Any], *, source: str) -> Config:
    top: dict[str, Any] = {}
    for key, value in data.items():
        key = RENAMED_KEYS.get(key, key)
        if key in AGENT_NAMES:
            if not isinstance(value, Mapping):
                raise ConfigError(f"{source}: [{key}] 는 테이블이어야 합니다")
            unknown = set(value) - _AGENT_KEYS
            if unknown:
                raise ConfigError(f"{source}: [{key}] 에 알 수 없는 키: {', '.join(sorted(unknown))}")
            value = dict(value)
            if "effort" in value and "step_effort" not in value:
                # effort 만 정한 층은 '모든 단계 같은 강도' (DESIGN.md 18.1 층 규칙)
                value["step_effort"] = {}
            if isinstance(value.get("step_effort"), Mapping):
                value["step_effort"] = dict(value["step_effort"])
            top[key] = replace(cfg.agent(key), **value)
        elif key in _TOP_LEVEL_KEYS:
            top[key] = value
        else:
            raise ConfigError(f"{source}: 알 수 없는 설정 키: {key}")
    return replace(cfg, **top)


def _nest(flat: Mapping[str, Any]) -> dict[str, Any]:
    """{"claude.model": "x"} → {"claude": {"model": "x"}}"""
    out: dict[str, Any] = {}
    for k, v in flat.items():
        if "." in k:
            head, tail = k.split(".", 1)
            sub = out.setdefault(head, {})
            if isinstance(sub, dict):
                sub[tail] = v
        else:
            if isinstance(v, Mapping) and isinstance(out.get(k), dict):
                out[k].update(v)
            else:
                out[k] = v
    return out


def parse_step_effort(text: str) -> dict[str, str]:
    """CLI 의 "review=high,fix=low" → {"review": "high", "fix": "low"}. 검증은 Config.validate 가 한다."""
    out: dict[str, str] = {}
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        step, sep, level = part.partition("=")
        if not sep or not step.strip() or not level.strip():
            raise ConfigError(f"단계별 추론 강도 형식이 잘못되었습니다: {part!r} (예: review=high,fix=low)")
        out[step.strip()] = level.strip()
    return out


def describe_effort(ac: AgentConfig) -> str:
    """시작 로그용: "medium; synthesize·review=high" """
    groups: dict[str, list[str]] = {}
    for step in EFFORT_STEPS:
        level = ac.step_effort.get(step)
        if level and level != ac.effort:
            groups.setdefault(level, []).append(step)
    parts = [ac.effort] if ac.effort else (["기본"] if groups else [])
    rest = ", ".join(f"{'·'.join(steps)}={level}" for level, steps in groups.items())
    return "; ".join(p for p in (", ".join(parts), rest) if p)
