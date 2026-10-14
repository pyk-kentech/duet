"""프롬프트 템플릿 로드/렌더링.

- 기본 템플릿: 패키지의 templates/*.md
- 사용자 커스터마이즈: <workdir>/.duet/templates/<같은 이름>.md 가 있으면 우선
- 플레이스홀더는 `{task}` 처럼 str.format 스타일. `{{`/`}}` 는 문자 그대로의 중괄호.
  이름이 없거나 공백이 섞인 중괄호(예: `{ "a": 1 }`)는 건드리지 않는다.
"""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

TEMPLATE_NAMES = ("propose", "critique", "synthesize", "implement", "fix", "review")
USER_TEMPLATE_DIR = Path(".duet") / "templates"

_PLACEHOLDER_RE = re.compile(r"\{\{|\}\}|\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class TemplateError(Exception):
    pass


def user_template_path(workdir: Path | None, name: str) -> Path | None:
    if workdir is None:
        return None
    p = Path(workdir) / USER_TEMPLATE_DIR / f"{name}.md"
    return p if p.is_file() else None


def load_template(name: str, workdir: Path | None = None) -> str:
    if name not in TEMPLATE_NAMES:
        raise TemplateError(f"알 수 없는 템플릿: {name} (가능: {', '.join(TEMPLATE_NAMES)})")
    user = user_template_path(workdir, name)
    if user is not None:
        return user.read_text(encoding="utf-8")
    ref = resources.files("duet").joinpath("templates", f"{name}.md")
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
