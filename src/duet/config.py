"""설정: 기본값 + <workdir>/duet.toml + CLI 인자 덮어쓰기.

우선순위: CLI 인자 > duet.toml > 기본값
"""

from __future__ import annotations

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


_TOKEN_RE = re.compile(r"^[A-Za-z0-9._:\[\]/-]{0,80}$")
EFFORT_SUGGESTIONS = {
    "claude": ["low", "medium", "high", "xhigh", "max"],
    "codex": ["minimal", "low", "medium", "high", "xhigh", "max"],
}
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
    model: str = ""     # 비우면 CLI 기본 모델
    effort: str = ""    # 추론 강도. 비우면 CLI 기본값


def _default_claude() -> AgentConfig:
    return AgentConfig(
        bin="claude",
        base_args=["-p", "--output-format", "json"],
        read_args=["--allowedTools", "Read,Glob,Grep"],
        write_args=[
            "--permission-mode", "acceptEdits",
            "--allowedTools", "Read,Edit,Write,Glob,Grep,Bash",
        ],
    )


def _default_codex() -> AgentConfig:
    return AgentConfig(
        bin="codex",
        base_args=["exec", "--skip-git-repo-check"],
        read_args=["--sandbox", "read-only"],
        write_args=["--sandbox", "workspace-write"],
    )


@dataclass
class Config:
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
    rate_limit_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_RATE_LIMIT_PATTERNS))
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
        if not isinstance(self.stall_rounds, int) or not 0 <= self.stall_rounds <= MAX_REVIEW_ROUNDS:
            raise ConfigError(f"stall_rounds 는 0~{MAX_REVIEW_ROUNDS} 사이여야 합니다: {self.stall_rounds}")
        for name in AGENT_NAMES:
            ac = self.agent(name)
            if not ac.bin:
                raise ConfigError(f"[{name}] bin 이 비어 있습니다")
            for key in ("base_args", "read_args", "write_args"):
                v = getattr(ac, key)
                if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                    raise ConfigError(f"[{name}] {key}는 문자열 리스트여야 합니다")
            for key in ("model", "effort"):
                v = getattr(ac, key)
                if not isinstance(v, str) or not _TOKEN_RE.match(v):
                    raise ConfigError(f"[{name}] {key} 값이 잘못되었습니다: {v!r} (영문·숫자·.-_:[]/ 만)")


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
            top[key] = replace(cfg.agent(key), **dict(value))
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
