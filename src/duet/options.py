"""설정 항목 정의 (DESIGN.md 28.4).

설정 화면의 '고급 설정' 카드와 새 실행 창의 '고급' 칸은 이 정의에서 만든다. 설정을 더하면 여기 한 줄로 UI 에 나온다.
기본 실행 설정(구현·리뷰·모델·테스트 명령 등)은 설정 화면이 직접 그리므로 BASIC_KEYS 에 둔다.
시험이 Config 의 필드를 모두 OPTIONS·BASIC_KEYS·NOT_IN_UI 중 하나에 두었는지 확인한다(UI 에서 빠지지 않게).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from duet.config import Config, ConfigError, load_config

GROUPS = {"run": "실행", "tools": "권한·도구", "review": "리뷰", "safety": "안전", "limits": "시간·한도"}
_TEXT_RE = re.compile(r"^[A-Za-z0-9._:\[\]/-]{0,80}$")


@dataclass(frozen=True)
class Option:
    key: str
    label: str
    help: str
    kind: str                       # bool | int | choice | text
    group: str
    choices: tuple[str, ...] = ()
    min: int | None = None
    max: int | None = None
    run_dialog: bool = True         # 새 실행 창의 '고급' 칸에도 보인다


OPTIONS: tuple[Option, ...] = (
    Option("workflow", "워크플로", "역할·단계 조합. classic 은 설정의 구현·리뷰 담당으로 만든다 (19장).", "choice", "run",
           run_dialog=False),
    Option("timeout_sec", "호출 시간 제한(초)", "에이전트 호출 하나가 이보다 오래 걸리면 멈춘다.", "int", "limits", min=60, max=86400),
    Option("test_timeout_sec", "테스트 시간 제한(초)", "duet 가 돌리는 테스트 명령의 시간 제한.", "int", "limits", min=10, max=86400),
    Option("max_diff_chars", "리뷰 diff 최대 글자 수", "넘으면 diff 를 자르고 파일 요약만 남긴다.", "int", "review", min=1000, max=2_000_000),
    Option("review_packet", "리뷰 패킷", "바뀐 함수 전체와 그 함수가 쓰이는 곳을 리뷰어에게 미리 보여 준다 (21.1).", "bool", "review"),
    Option("review_json", "JSON 판정", "리뷰 판정을 출력 스키마(JSON)로 받는다. 지적 원장·관문·중재의 전제 (21.2).", "bool", "review"),
    Option("review_session", "리뷰어 세션", "fresh: 라운드마다 새 세션(기본, 실측에서 더 쌌다). reuse: 2라운드부터 이어서 (21.3).",
           "choice", "review", ("fresh", "reuse")),
    Option("review_session_rounds", "세션 재사용 상한", "reuse 일 때 한 세션을 쓰는 최대 라운드 수.", "int", "review", min=1, max=10),
    Option("review_gates", "판정 관문", "근거 없는 막는 지적, 2라운드부터 범위 밖 새 지적을 P3 로 낮춘다 (22장).", "bool", "review"),
    Option("spec_gate", "요구 근거 관문", "취향 지적, 과제·설계에서 찾을 수 없는 요구 인용을 P3 로 낮춘다 (25.2).", "bool", "review"),
    Option("arbiter", "분쟁 중재자", "리뷰가 수렴하지 않거나 상한에 닿으면 한 번 열린 지적을 정리한다 (23장).", "bool", "review"),
    Option("access", "에이전트 권한", "full: 모든 도구·명령·네트워크(작업 폴더 밖 변경도 막지 않음). standard: 읽기 단계는 읽기 도구만, "
           "쓰기 단계는 편집·명령, Codex 는 샌드박스 (33.5).", "choice", "tools", ("full", "standard"), run_dialog=True),
    Option("web_search", "웹 검색", "최신 문서·API·버전을 웹에서 찾게 한다. 권한 standard 면 읽기 단계에서만 (33.1).", "choice", "tools",
           ("on", "off"), run_dialog=True),
    Option("package_lookup", "패키지 버전 조회", "권한 standard 의 읽기 단계에 npm view·pip index versions 같은 조회 명령만 허용 (33.2).",
           "bool", "tools"),
    Option("browser_check", "브라우저 확인", "auto: 웹 화면이 있는 프로젝트면 리뷰 때 앱을 띄우고 리뷰어가 필요하면 브라우저로 확인 (33.4).",
           "choice", "tools", ("auto", "off"), run_dialog=True),
    Option("report", "결과 요약", "실행이 끝나면 작은 모델이 만든 것과 실행 방법을 정리한다 (32장).", "bool", "run"),
    Option("report_agent", "결과 요약 CLI", "결과 요약에 쓸 CLI.", "choice", "run", ("claude", "codex")),
    Option("report_model", "결과 요약 모델", "결과 요약 모델(작은 모델 권장).", "text", "run"),
    Option("report_effort", "결과 요약 추론 강도", "비우면 CLI 기본값.", "text", "run"),
    Option("dedup", "재제기·되돌림 방지", "해결·기각된 지적의 반복을 작은 모델로 확인하고, 되돌린 코드를 경고한다 (26장).", "bool", "review"),
    Option("dedup_agent", "중복 확인 CLI", "재제기 확인에 쓸 CLI.", "choice", "review", ("claude", "codex")),
    Option("dedup_model", "중복 확인 모델", "재제기 확인 모델(작은 모델 권장).", "text", "review"),
    Option("dedup_effort", "중복 확인 추론 강도", "비우면 CLI 기본값.", "text", "review"),
    Option("test_guard", "테스트 변조 감지", "테스트를 지우거나 약하게 만든 흔적을 리뷰어·중재자에게 경고한다 (24.1).", "bool", "safety"),
    Option("claude_sandbox", "Claude 샌드박스", "Claude 구현자의 명령을 OS 샌드박스에서 돌린다. Linux 는 bubblewrap·socat 필요 (24.3).",
           "bool", "safety"),
    Option("wait_on_limit", "한도 대기 후 재개", "구독 한도에 걸리면 멈추지 않고 재개 시각까지 기다렸다가 이어간다 (25.1).", "bool", "limits"),
    Option("limit_wait_max_min", "최대 대기(분)", "한 실행에서 한도 대기에 쓸 수 있는 시간 합.", "int", "limits", min=1, max=10080),
)
BY_KEY = {o.key: o for o in OPTIONS}

# 설정 화면의 '기본 실행 설정' 카드가 직접 그리는 것
BASIC_KEYS = ("implementer", "reviewer", "synth", "debate_rounds", "max_review", "claude", "codex", "test_command",
              "block_severity", "stall_rounds", "require_tests_pass", "review_diff", "repro_tests",
              "step_overrides")   # step_overrides: 새 실행 창 순서도의 칸에서 고른다 (DESIGN.md 30.5)
# UI 에서 바꾸지 않는 것 (duet.toml 로만)
NOT_IN_UI = ("env_strip", "env_keep", "rate_limit_patterns", "diff_excludes", "prompt_arg_max_bytes")


class OptionError(ValueError):
    pass


def parse(key: str, raw: Any) -> Any:
    """화면·CLI 에서 온 값 → 설정 값. 빈 값이면 None(기본값 사용)."""
    o = BY_KEY.get(key)
    if o is None:
        raise OptionError(f"알 수 없는 설정입니다: {key}")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if o.kind == "bool":
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in ("true", "1", "yes", "on", "켬"):
            return True
        if s in ("false", "0", "no", "off", "끔"):
            return False
        raise OptionError(f"{o.label}: 참/거짓 값이어야 합니다: {raw!r}")
    if o.kind == "int":
        try:
            v = int(str(raw).strip())
        except ValueError:
            raise OptionError(f"{o.label}: 숫자여야 합니다: {raw!r}") from None
        if (o.min is not None and v < o.min) or (o.max is not None and v > o.max):
            raise OptionError(f"{o.label}: {o.min}~{o.max} 사이여야 합니다: {v}")
        return v
    s = str(raw).strip()
    if o.kind == "choice" and o.choices and s not in o.choices:
        raise OptionError(f"{o.label}: {', '.join(o.choices)} 중 하나여야 합니다: {s!r}")
    if not _TEXT_RE.match(s):
        raise OptionError(f"{o.label}: 값이 잘못되었습니다: {s!r}")
    return s


def parse_assignments(items: list[str] | None) -> dict[str, Any]:
    """CLI `--set 키=값` 목록 → 설정 덮어쓰기."""
    out: dict[str, Any] = {}
    for item in items or []:
        key, sep, raw = item.partition("=")
        if not sep:
            raise OptionError(f"--set 은 키=값 형식이어야 합니다: {item!r}")
        v = parse(key.strip(), raw)
        if v is not None:
            out[key.strip()] = v
    return out


def clean(values: dict[str, Any]) -> dict[str, Any]:
    """화면에서 온 {키: 값} 중 정의된 것만, 빈 값은 빼고."""
    out = {}
    for k, raw in (values or {}).items():
        if k in BY_KEY:
            v = parse(k, raw)
            if v is not None:
                out[k] = v
    return out


def to_cli(value: Any) -> str:
    return ("true" if value else "false") if isinstance(value, bool) else str(value)


def schema(cfg: Config | None = None, workflows: list[str] | None = None) -> list[dict[str, Any]]:
    """화면이 그릴 정의 + 지금 적용되는 값."""
    if cfg is None:
        try:
            cfg = load_config(None)
        except ConfigError:
            cfg = Config()
    builtin = Config()
    out = []
    order = list(GROUPS)
    for o in sorted(OPTIONS, key=lambda o: order.index(o.group)):     # 묶음 순서대로 (정렬은 안정적)
        d = asdict(o)
        if o.key == "workflow" and workflows:
            d["choices"] = list(workflows)
        d["effective"] = getattr(cfg, o.key)
        d["default"] = getattr(builtin, o.key)            # duet 내장 기본값 (설정 화면의 '기본값으로')
        d["group_label"] = GROUPS[o.group]
        out.append(d)
    return out
