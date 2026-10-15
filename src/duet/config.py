"""설정: 기본값 + <workdir>/duet.toml + CLI 인자 덮어쓰기.

우선순위: CLI 인자 > duet.toml > 기본값
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Mapping

AGENT_NAMES = ("claude", "codex")

MAX_DEBATE_ROUNDS = 5
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


class ConfigError(Exception):
    """설정 값이 잘못됨."""


@dataclass
class AgentConfig:
    bin: str
    base_args: list[str] = field(default_factory=list)
    read_args: list[str] = field(default_factory=list)
    write_args: list[str] = field(default_factory=list)


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
        for name in AGENT_NAMES:
            ac = self.agent(name)
            if not ac.bin:
                raise ConfigError(f"[{name}] bin 이 비어 있습니다")
            for key in ("base_args", "read_args", "write_args"):
                v = getattr(ac, key)
                if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                    raise ConfigError(f"[{name}] {key}는 문자열 리스트여야 합니다")


CONFIG_FILENAME = "duet.toml"

_TOP_LEVEL_KEYS = {
    f.name for f in fields(Config) if f.name not in AGENT_NAMES
}
_AGENT_KEYS = {f.name for f in fields(AgentConfig)}


def load_config(
    workdir: Path | str | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> Config:
    """기본값 → duet.toml → overrides 순으로 덮어쓴 Config를 돌려준다.

    overrides의 None 값은 '지정 안 함'으로 보고 무시한다(CLI 인자 기본값 None 대응).
    """
    cfg = Config()
    if workdir is not None:
        path = Path(workdir) / CONFIG_FILENAME
        if path.is_file():
            cfg = _apply(cfg, _read_toml(path), source=str(path))
    if overrides:
        cfg = _apply(cfg, {k: v for k, v in overrides.items() if v is not None}, source="CLI 인자")
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
