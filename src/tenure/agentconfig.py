"""에이전트 설정 보기 (DESIGN.md 36.19, NotchCrew 아이디어): 그 폴더에서 Claude·Codex 가 실제로 읽는 것.

보기 전용이다. 파일을 고치지 않는다. 비밀값(환경 변수 값·헤더·토큰처럼 보이는 인자)은 가린다.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

from tenure.usage import claude_home, codex_home

MASK = "••••"
MAX_LIST = 80
SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{12,}|xox[abpr]-[A-Za-z0-9-]{8,}|"
                       r"(?i:(?:token|key|secret|password|passwd|auth)[=:])\S+|[A-Za-z0-9+/_-]{32,})")
SECRET_KEY_RE = re.compile(r"(?i)token|key|secret|password|passwd|auth|credential|cookie")


def _mask(v: Any) -> Any:
    if isinstance(v, str):
        return SECRET_RE.sub(MASK, v)
    if isinstance(v, list):
        return [_mask(x) for x in v][:MAX_LIST]
    return v


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _md_info(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    first = next((ln.strip("# ").strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("---")), "")
    return {"path": str(path), "chars": len(text), "first_line": first[:160]}


def _frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    out = {}
    for ln in (m.group(1).splitlines() if m else []):
        if ":" in ln:
            k, v = ln.split(":", 1)
            out[k.strip()] = v.strip().strip("'\"")
    return out


def _items(folder: Path, pattern: str, where: str) -> list[dict[str, Any]]:
    out = []
    if folder.is_dir():
        for p in sorted(folder.glob(pattern))[:MAX_LIST]:
            fm = _frontmatter(p)
            name = fm.get("name") or (p.parent.name if p.name.upper() == "SKILL.MD" else p.stem)
            out.append({"name": name, "description": (fm.get("description") or "")[:200], "where": where, "path": str(p)})
    return out


def _mcp(servers: Any, where: str) -> list[dict[str, Any]]:
    out = []
    for name, cfg in (servers or {}).items() if isinstance(servers, dict) else []:
        if not isinstance(cfg, dict):
            continue
        out.append({"name": name, "where": where, "type": cfg.get("type") or ("http" if cfg.get("url") else "stdio"),
                    "command": _mask(cfg.get("command") or cfg.get("url") or ""), "args": _mask(cfg.get("args") or []),
                    "env": sorted((cfg.get("env") or {}).keys()), "headers": sorted((cfg.get("headers") or {}).keys())})
    return out


def _settings_summary(path: Path, where: str) -> dict[str, Any] | None:
    data = _read_json(path)
    if data is None:
        return None
    perms = data.get("permissions") or {}
    hooks = data.get("hooks") or {}
    return {"where": where, "path": str(path),
            "model": data.get("model"),
            "permissions": {k: _mask(perms.get(k) or []) for k in ("allow", "deny", "ask") if perms.get(k)},
            "default_mode": perms.get("defaultMode"),
            "hooks": {ev: [_mask(h.get("command", "")) for g in (groups or []) for h in (g.get("hooks") or [])]
                      for ev, groups in hooks.items() if isinstance(groups, list)},
            "env": sorted((data.get("env") or {}).keys()),
            "plugins": sorted(k for k, v in (data.get("enabledPlugins") or {}).items() if v),
            "other_keys": sorted(k for k in data if k not in ("permissions", "hooks", "env", "enabledPlugins", "model"))}


def _upward(project: Path, names: tuple[str, ...]) -> list[Path]:
    """작업 폴더에서 위로 올라가며 (CLI 는 상위 폴더의 메모리 파일도 읽는다)."""
    out: list[Path] = []
    for d in [project, *project.parents]:
        for n in names:
            if (d / n).is_file():
                out.append(d / n)
        if (d / ".git").exists():
            break
    return out


def claude_config(project: Path) -> dict[str, Any]:
    home = claude_home()
    user_json = _read_json(home.parent / ".claude.json") if home == Path.home() / ".claude" else _read_json(home / ".claude.json")
    proj_entry = {}
    for k, v in ((user_json or {}).get("projects") or {}).items():
        if Path(k).resolve() == project.resolve() and isinstance(v, dict):
            proj_entry = v
    settings = [x for x in (_settings_summary(home / "settings.json", "사용자"),
                            _settings_summary(project / ".claude" / "settings.json", "프로젝트"),
                            _settings_summary(project / ".claude" / "settings.local.json", "프로젝트(로컬)")) if x]
    memory = [m for m in (_md_info(home / "CLAUDE.md"),
                          *(_md_info(p) for p in _upward(project, ("CLAUDE.md", "CLAUDE.local.md"))),
                          _md_info(project / ".claude" / "CLAUDE.md")) if m]
    return {
        "settings": settings,
        "memory": memory,
        "skills": _items(home / "skills", "*/SKILL.md", "사용자") + _items(project / ".claude" / "skills", "*/SKILL.md", "프로젝트"),
        "agents": _items(home / "agents", "*.md", "사용자") + _items(project / ".claude" / "agents", "*.md", "프로젝트"),
        "commands": _items(home / "commands", "**/*.md", "사용자") + _items(project / ".claude" / "commands", "**/*.md", "프로젝트"),
        "mcp": _mcp((user_json or {}).get("mcpServers"), "사용자") + _mcp(proj_entry.get("mcpServers"), "이 폴더(사용자 설정)")
        + _mcp((_read_json(project / ".mcp.json") or {}).get("mcpServers"), "프로젝트 .mcp.json"),
        "allowed_tools": _mask(proj_entry.get("allowedTools") or []),
    }


def codex_config(project: Path) -> dict[str, Any]:
    home = codex_home()
    try:
        data = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    proj = {}
    for k, v in (data.get("projects") or {}).items():
        try:
            if Path(k).resolve() == project.resolve() and isinstance(v, dict):
                proj = v
        except OSError:
            continue
    memory = [m for m in (_md_info(home / "AGENTS.md"), *(_md_info(p) for p in _upward(project, ("AGENTS.md", "AGENTS.override.md")))) if m]
    plain = {k: _mask(v) for k, v in data.items()
             if not isinstance(v, (dict, list)) and not SECRET_KEY_RE.search(k)}
    return {
        "path": str(home / "config.toml"),
        "settings": plain,
        "this_folder": {k: _mask(v) for k, v in proj.items() if not isinstance(v, dict)},
        "notify": _mask(data.get("notify") or []),
        "profiles": sorted((data.get("profiles") or {}).keys()),
        "memory": memory,
        "skills": _items(home / "skills", "*/SKILL.md", "사용자") + _items(project / ".codex" / "skills", "*/SKILL.md", "프로젝트"),
        "prompts": _items(home / "prompts", "*.md", "사용자"),
        "mcp": _mcp(data.get("mcp_servers"), "사용자"),
        "plugins": sorted((data.get("plugins") or {}).keys()) if isinstance(data.get("plugins"), dict) else [],
    }


def agent_config(project: Path) -> dict[str, Any]:
    project = Path(project)
    return {"project": str(project), "claude": claude_config(project), "codex": codex_config(project)}
