from pathlib import Path

import pytest

from duet.prompts import TEMPLATE_NAMES, TemplateError, load_template, render, render_text


def test_all_builtin_templates_load():
    for name in TEMPLATE_NAMES:
        assert load_template(name).strip()


def test_render_task():
    out = render("propose", task="메모 CLI")
    assert "과제: 메모 CLI" in out and "{task}" not in out


def test_review_template_has_verdict_block():
    out = render("review", task="t", diff="d", implementer_name="claude", tests="T", previous_review="P",
                 diff_title="구현 전체 diff", test_instruction="I", repro_instruction="R",
                 design_doc="DESIGN.md", design_note="")
    assert "<verdict>" in out and "must_fix" in out and "p3:" in out and "[P1]" in out


def test_missing_placeholder_raises():
    with pytest.raises(TemplateError, match="other_name"):
        render("critique", task="t", own="a", other="b")


def test_unknown_braces_left_alone():
    assert render_text("{task} 와 {{json}} 그리고 { 공백 }", task="X") == "X 와 {json} 그리고 { 공백 }"


def test_unknown_template():
    with pytest.raises(TemplateError):
        load_template("nope")


def test_user_override(tmp_path: Path):
    d = tmp_path / ".duet" / "templates"
    d.mkdir(parents=True)
    (d / "propose.md").write_text("내 템플릿: {task}", encoding="utf-8")
    assert render("propose", tmp_path, task="T") == "내 템플릿: T"
    # 다른 템플릿은 기본값
    assert "설계 토론" in render("critique", tmp_path, task="T", own="", other="", other_name="x")
