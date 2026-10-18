"""에이전트 권한과 도구 (DESIGN.md 33장).

권한 수준(access), 웹 검색, 패키지 버전 조회, 브라우저 확인 도구를 CLI 인자로 바꾼다. 어댑터는 이 함수만 쓴다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Sequence

from duet.agents.base import Mode

WEB_TOOLS = ("WebSearch", "WebFetch")
EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")
# 권한 standard 의 읽기 단계에 여는 조회 전용 명령 (33.2)
PACKAGE_LOOKUP_TOOLS = ("Bash(npm view:*)", "Bash(npm info:*)", "Bash(pip index versions:*)",
                        "Bash(cargo search:*)", "Bash(go list -m -versions:*)")
NO_WEB_STEPS = ("dedup", "report")        # 대조·요약만 하는 보조 호출
PLAYWRIGHT = "playwright"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def web_allowed(cfg, step: str, mode: Mode) -> bool:
    """이 호출에 웹 검색을 줄까 (33.1): full 이면 모든 단계, standard 면 읽기 단계만."""
    if getattr(cfg, "web_search", "off") != "on" or step in NO_WEB_STEPS:
        return False
    return cfg.access == "full" or mode is Mode.READ


def can_run_commands(cfg, read_args: Sequence[str]) -> bool:
    """읽기 단계에서 명령을 돌릴 수 있는가 (19.6): full 이면 언제나."""
    return cfg.access == "full" or any("Bash" in a for a in read_args)


def add_allowed(args: Sequence[str], extra: Sequence[str]) -> list[str]:
    """`--allowedTools a,b` 뒤에 도구를 더한다(가변 인자). 없으면 새로 붙인다."""
    out = list(args)
    if not extra:
        return out
    for flag in ("--allowedTools", "--allowed-tools"):
        if flag in out:
            i = out.index(flag) + 1
            while i < len(out) and not out[i].startswith("-"):
                i += 1
            return [*out[:i], *extra, *out[i:]]
    return [*out, "--allowedTools", *extra]


@dataclass
class Browser:
    """리뷰어에게 붙이는 브라우저 도구(Playwright MCP)와 띄운 앱 주소 (33.4)."""
    url: str
    command: str
    args: list[str] = field(default_factory=list)

    def claude_args(self) -> list[str]:
        cfg = json.dumps({"mcpServers": {PLAYWRIGHT: {"command": self.command, "args": self.args}}})
        return ["--mcp-config", cfg]

    def codex_args(self) -> list[str]:
        # TOML 값: 문자열·문자열 배열은 JSON 표기와 같다
        return ["-c", f"mcp_servers.{PLAYWRIGHT}.command={json.dumps(self.command)}",
                "-c", f"mcp_servers.{PLAYWRIGHT}.args={json.dumps(self.args)}"]

    def prompt_note(self) -> str:
        return ("## 브라우저로 확인 (duet 가 앱을 띄워 둠)\n\n"
                f"앱이 {self.url} 에서 돌고 있다. 화면·동작을 직접 봐야 판단할 수 있는 부분이 있으면 브라우저 도구"
                f"({PLAYWRIGHT})로 열어 확인하고, 본 것(무엇을 눌렀고 어떻게 보였는지)을 지적의 근거로 적어라. "
                "필요 없으면 쓰지 않아도 된다.")


def claude_mode_args(cfg, ac, req) -> list[str]:
    """Claude 의 권한·도구 인자. full 은 권한 우회 + 단계별로 뺄 도구, standard 는 설정의 인자 + 더할 도구."""
    read = req.mode is Mode.READ
    web = web_allowed(cfg, req.step, req.mode)
    if cfg.access == "full":
        args = ["--permission-mode", "bypassPermissions"]
        deny = [*(EDIT_TOOLS if read else ()), *(() if web else WEB_TOOLS)]
        if deny:
            args += ["--disallowedTools", ",".join(deny)]
    else:
        args = list(ac.read_args if read else ac.write_args)
        if req.resume_session and ac.resume_read_args and read:
            args = list(ac.resume_read_args)
        extra = [*(WEB_TOOLS if web else ()), *(PACKAGE_LOOKUP_TOOLS if read and cfg.package_lookup else ())]
        if req.browser is not None:
            extra.append(f"mcp__{PLAYWRIGHT}")
        args = add_allowed(args, extra)
    if req.browser is not None:
        args += req.browser.claude_args()
    return args


def codex_top_args(cfg, req) -> list[str]:
    """`codex` 바로 뒤(하위 명령 앞)에 붙는 인자: 웹 검색 (33.1)."""
    return ["--search"] if web_allowed(cfg, req.step, req.mode) else []


def codex_mode_args(cfg, ac, req, *, resume: bool) -> list[str]:
    """Codex 의 권한 인자 + 첨부 이미지 + 브라우저 도구."""
    if cfg.access == "full":
        args = ["--dangerously-bypass-approvals-and-sandbox"]
    elif resume:
        args = list(ac.resume_read_args or ac.read_args)
    else:
        args = list(ac.read_args if req.mode is Mode.READ else ac.write_args)
    for img in req.images:
        args += ["-i", str(img)]
    if req.browser is not None:
        args += req.browser.codex_args()
    return args
