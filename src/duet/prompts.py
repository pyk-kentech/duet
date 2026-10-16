"""프롬프트 템플릿 로드/렌더링.

- 찾는 순서: <workdir>/.duet/templates/<이름>.md → $DUET_HOME/templates/<이름>.md → 패키지 templates/<이름>.md
  (같은 이름이면 앞이 우선. 워크플로 역할은 새 이름의 템플릿을 쓸 수 있다 — DESIGN.md 19.4)
- 플레이스홀더는 `{task}` 처럼 str.format 스타일. `{{`/`}}` 는 문자 그대로의 중괄호.
  이름이 없거나 공백이 섞인 중괄호(예: `{ "a": 1 }`)는 건드리지 않는다.
"""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

TEMPLATE_NAMES = ("propose", "critique", "synthesize", "implement", "fix", "review",
                  "explore", "audit", "review_security", "rereview")
USER_TEMPLATE_DIR = Path(".duet") / "templates"
TEMPLATE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

_PLACEHOLDER_RE = re.compile(r"\{\{|\}\}|\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class TemplateError(Exception):
    pass


def user_template_path(workdir: Path | None, name: str) -> Path | None:
    if workdir is None:
        return None
    p = Path(workdir) / USER_TEMPLATE_DIR / f"{name}.md"
    return p if p.is_file() else None


def home_template_path(name: str) -> Path | None:
    from duet.registry import duet_home

    p = duet_home() / "templates" / f"{name}.md"
    return p if p.is_file() else None


def _builtin(name: str):
    ref = resources.files("duet").joinpath("templates", f"{name}.md")
    return ref if ref.is_file() else None


def template_exists(name: str, workdir: Path | None = None) -> bool:
    if not TEMPLATE_NAME_RE.match(name):
        return False
    return bool(user_template_path(workdir, name) or home_template_path(name) or _builtin(name))


def load_template(name: str, workdir: Path | None = None) -> str:
    if not TEMPLATE_NAME_RE.match(name):
        raise TemplateError(f"템플릿 이름이 잘못되었습니다: {name!r} (영문 소문자·숫자·_ 만)")
    for path in (user_template_path(workdir, name), home_template_path(name)):
        if path is not None:
            return path.read_text(encoding="utf-8")
    ref = _builtin(name)
    if ref is None:
        raise TemplateError(f"템플릿을 찾을 수 없습니다: {name} "
                            f"(<작업 폴더>/.duet/templates/, $DUET_HOME/templates/, 내장 중 어디에도 없음)")
    return ref.read_text(encoding="utf-8")


def render_text(template: str, **values: object) -> str:
    missing: list[str] = []

    def sub(m: re.Match[str]) -> str:
        if m.group(0) == "{{":
            return "{"
        if m.group(0) == "}}":
            return "}"
        key = m.group(1)
        if key in values:
            return str(values[key])
        missing.append(key)
        return m.group(0)

    out = _PLACEHOLDER_RE.sub(sub, template)
    if missing:
        raise TemplateError(f"템플릿에 값이 없는 플레이스홀더: {', '.join(sorted(set(missing)))}")
    return out


def render(name: str, workdir: Path | None = None, **values: object) -> str:
    return render_text(load_template(name, workdir), **values)
