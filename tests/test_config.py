from pathlib import Path

import pytest

from tenure.config import Config, ConfigError, load_config


def test_defaults():
    cfg = load_config(None)
    assert cfg.implementer == "claude" and cfg.reviewer == "codex"
    assert cfg.synth is None and cfg.synth_name == "codex"
    assert cfg.debate_rounds == 1 and cfg.max_review == 3
    assert cfg.timeout_sec == 1200 and cfg.max_diff_chars == 60_000
    assert cfg.claude.bin == "claude" and cfg.codex.bin == "codex"
    assert "--output-format" in cfg.claude.base_args
    assert cfg.codex.read_args == ["--sandbox", "read-only"]


def test_toml_overrides(tmp_path: Path):
    (tmp_path / "tenure.toml").write_text(
        'implementer = "codex"\nreviewer = "claude"\ndebate_rounds = 2\n\n'
        '[claude]\nbin = "/opt/claude"\nread_args = ["--allowedTools", "Read"]\n',
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.implementer == "codex" and cfg.reviewer == "claude"
    assert cfg.synth_name == "claude"
    assert cfg.debate_rounds == 2
    assert cfg.claude.bin == "/opt/claude"
    assert cfg.claude.read_args == ["--allowedTools", "Read"]
    # 지정 안 한 값은 기본값 유지
    assert cfg.claude.write_args[0] == "--permission-mode"
    assert cfg.codex.bin == "codex"


def test_cli_beats_toml(tmp_path: Path):
    (tmp_path / "tenure.toml").write_text("max_review = 5\ndebate_rounds = 2\n", encoding="utf-8")
    cfg = load_config(tmp_path, {"max_review": 4, "debate_rounds": None, "synth": "claude"})
    assert cfg.max_review == 4          # CLI 우선
    assert cfg.debate_rounds == 2       # None 은 '지정 안 함'
    assert cfg.synth == "claude"


def test_missing_toml_is_fine(tmp_path: Path):
    assert load_config(tmp_path).max_review == 3


@pytest.mark.parametrize(
    "overrides",
    [
        {"debate_rounds": 6},
        {"debate_rounds": -1},
        {"max_review": 0},
        {"max_review": 11},
        {"implementer": "gpt"},
        {"implementer": "codex"},  # reviewer 기본값 codex 와 같음
        {"synth": "gemini"},
        {"timeout_sec": 0},
        {"claude": {"bin": ""}},
        {"codex": {"read_args": "oops"}},
    ],
)
def test_validation_errors(overrides):
    with pytest.raises(ConfigError):
        load_config(None, overrides)


def test_unknown_keys_rejected(tmp_path: Path):
    (tmp_path / "tenure.toml").write_text("typo_key = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="typo_key"):
        load_config(tmp_path)
    (tmp_path / "tenure.toml").write_text("[claude]\nbinary = 'x'\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="binary"):
        load_config(tmp_path)


def test_bad_toml(tmp_path: Path):
    (tmp_path / "tenure.toml").write_text("= broken", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_agent_lookup():
    cfg = Config()
    assert cfg.agent("claude") is cfg.claude
    with pytest.raises(ConfigError):
        cfg.agent("nope")
