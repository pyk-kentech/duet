# duet — 설계 토론 + 교차 리뷰 에이전트 팀

> 구독 중인 Claude(Claude Code CLI)와 ChatGPT(Codex CLI)를 API 키 없이 헤드리스로 호출해,
> 두 모델이 **설계를 토론**하고 **서로의 코드를 교차 리뷰**하며 프로젝트를 완성하게 만드는 로컬 CLI 도구.

---

## 1. 목표와 범위

### 목표
- 한 줄(또는 파일) 과제를 받아 다음을 자동 진행한다.
  1. **설계 토론**: 두 모델이 각자 설계안 → 상호 비판·개정(N라운드) → 결정권자가 `DESIGN.md` 종합
  2. **구현 + 교차 리뷰**: 구현 담당이 코드 작성 → 리뷰 담당이 리뷰 → 승인될 때까지 수정 반복(최대 M회)
- 모든 발언·판정·커밋을 기록해서, 나중에 "둘이 어떻게 논쟁했는지" 읽을 수 있게 한다.
- 중간에 멈춰도 **이어서 재개**할 수 있다.
- 실제 CLI 없이도 전체 흐름을 테스트할 수 있다(mock).

### 비목표 (하지 않을 것)
- 웹 UI, 서버, 데이터베이스
- 유료 API 직접 호출 (Anthropic/OpenAI SDK 사용 안 함)
- chatgpt.com / claude.ai 웹 화면 자동화 (약관 위험 + 취약)
- 3개 이상 에이전트, 병렬 실행 (v2 후보로만 남김)

---

## 2. 사용 시나리오

```bash
# 전체 실행
duet run "마크다운 메모를 태그로 검색하는 CLI" --workdir ./memo-cli

# 긴 과제는 파일로
duet run @task.md --workdir ./memo-cli

# 설계 토론만 보고 싶을 때
duet run "..." --workdir ./x --design-only

# 사람이 DESIGN.md를 손본 뒤 구현부터
duet run "..." --workdir ./x --skip-design

# 역할 바꾸기
duet run "..." --workdir ./x --implementer codex --reviewer claude

# 중단된 실행 이어하기 (마지막 run 기준, --run <id> 로 특정 run)
duet resume --workdir ./x

# 리뷰 상한을 다 써서 미승인으로 끝난 실행을, 상한을 늘려 마지막 리뷰 반영부터 이어가기
duet resume --workdir ./x --max-review 3

# 지난 실행 기록 보기
duet log --workdir ./x            # 최근 run 요약
duet log --workdir ./x --full     # 전체 발언을 순서대로 출력
duet log --workdir ./x --all      # 모든 run 한 줄씩

# CLI 없이 흐름 테스트
duet run "..." --workdir ./x --mock
```

실행 중 터미널에는 단계별 진행 상황(누가 무엇을 하는 중인지, 소요 시간, 판정)이 한 줄씩 찍힌다.

종료 코드: 0 승인 완료/설계만 완료, 1 미승인 종료, 2 사용 오류, 3 중단(한도·반복 실패 → `resume`).

---

## 3. 아키텍처

```
          ┌────────────── duet CLI (cli.py) ──────────────┐
          │  run / resume / log                            │
          └───────────────┬───────────────────────────────┘
                          ▼
                ┌───────────────────┐       ┌──────────────┐
                │   Orchestrator    │──────▶│  RunState    │ (run.json, 재개용)
                └──┬──────────┬─────┘       └──────────────┘
                   │          │
        ┌──────────▼──┐  ┌────▼─────────┐   ┌──────────────┐
        │ DebatePhase │  │ BuildPhase   │──▶│  Workspace   │ (git 래퍼)
        └──────┬──────┘  └────┬─────────┘   └──────────────┘
               │              │
               ▼              ▼
        ┌─────────────────────────────┐     ┌──────────────┐
        │  AgentAdapter (프로토콜)      │────▶│  Transcript  │ (발언 기록)
        │  ├ ClaudeCodeAdapter        │     └──────────────┘
        │  ├ CodexAdapter             │
        │  └ MockAdapter              │     ┌──────────────┐
        └─────────────────────────────┘     │  Prompts     │ (템플릿 파일)
                                            └──────────────┘
```

### 핵심 원칙
- **에이전트 어댑터는 얇게**: 명령어 조립 → 실행 → 결과 파싱만. 판단 로직은 Phase에.
- **모든 외부 실행은 `runner.run_process()` 한 곳을 지난다**: 타임아웃, 로그, 테스트용 가짜 실행 주입이 여기서 해결됨.
- **상태는 단계가 끝날 때마다 디스크에 저장**: 어느 지점에서 죽어도 resume 가능.
- **리뷰어는 코드를 못 바꾼다**: CLI 샌드박스 + git으로 이중 확인.

---

## 4. 디렉터리 구조

```
duet/
├── CLAUDE.md
├── DESIGN.md
├── README.md
├── pyproject.toml              # 엔트리포인트 `duet`, 의존성 없음 (dev: pytest)
├── prototype/
│   └── agent_team.py           # 참고용 단일 파일 프로토타입 (수정하지 말 것)
├── src/duet/
│   ├── __init__.py
│   ├── cli.py                  # argparse, 서브커맨드
│   ├── config.py               # 기본값 + duet.toml 로드
│   ├── orchestrator.py         # 단계 진행, resume
│   ├── state.py                # RunState 직렬화
│   ├── transcript.py           # 발언 기록
│   ├── workspace.py            # git 조작
│   ├── runner.py               # subprocess 실행 공통부
│   ├── verdict.py              # 리뷰 판정 파싱
│   ├── prompts.py              # 템플릿 로드/렌더링
│   ├── phases/
│   │   ├── debate.py
│   │   └── build.py
│   ├── agents/
│   │   ├── base.py             # AgentAdapter 프로토콜, Request/Result
│   │   ├── claude_code.py
│   │   ├── codex.py
│   │   └── mock.py
│   └── templates/              # 프롬프트 .md 파일들
│       ├── propose.md
│       ├── critique.md
│       ├── synthesize.md
│       ├── implement.md
│       ├── fix.md
│       └── review.md
└── tests/
    ├── fake_bin/               # 가짜 claude, codex 실행 파일 (셸/파이썬 스크립트)
    ├── test_verdict.py
    ├── test_agents.py          # 명령어 조립 + 출력 파싱
    ├── test_workspace.py
    ├── test_debate.py
    ├── test_build.py
    └── test_e2e_mock.py
```

---

## 5. 인터페이스

### 5.1 에이전트

```python
class Mode(Enum):
    READ = "read"     # 파일 읽기만 허용 (설계, 리뷰)
    WRITE = "write"   # 파일 수정 + 셸 실행 허용 (구현, 수정)

@dataclass
class AgentRequest:
    prompt: str
    cwd: Path
    mode: Mode
    timeout_sec: int
    step: str = ""         # "propose" | "critique" | ... 기록용. MockAdapter가 응답을 고르는 기준

@dataclass
class AgentResult:
    text: str              # 최종 응답 본문
    raw_stdout: str
    raw_stderr: str
    exit_code: int
    duration_sec: float
    rate_limited: bool     # 구독 한도 걸림 감지 여부
    timed_out: bool        # 타임아웃으로 강제 종료됨 (exit_code=-1)
    # ok 프로퍼티: exit_code==0 and not timed_out and not rate_limited

class AgentAdapter(Protocol):
    name: str              # "claude" | "codex" | "mock-claude" ...
    def check(self) -> None: ...                   # 설치/로그인 확인, 실패 시 친절한 에러
    def ask(self, req: AgentRequest) -> AgentResult: ...
```

### 5.2 CLI별 호출 방식 (✅ 2026-10-15, Claude Code 2.1.300 / codex-cli 0.162.1 의 `--help`로 검증 완료)

| 항목 | Claude Code | Codex CLI |
|---|---|---|
| 헤드리스 실행 | `claude -p [옵션] -- <prompt>` | `codex exec [옵션] <prompt>` |
| 결과 받기 | `--output-format json` → `.result` | `--output-last-message <file>` |
| 작업 디렉터리 | `cwd`로 지정 | `-C <dir>` (+ `--skip-git-repo-check`) |
| READ 모드 | `--allowedTools Read,Glob,Grep` | `--sandbox read-only` |
| WRITE 모드 | `--permission-mode acceptEdits --allowedTools Read,Edit,Write,Glob,Grep,Bash` | `--sandbox workspace-write` |

- 플래그는 어댑터 안에 하드코딩하지 말고 `config.py`의 기본값으로 두어, 버전 차이가 나면 `duet.toml`로 덮어쓸 수 있게 한다.
- 프롬프트가 매우 길어질 수 있으므로(설계안 2개 + 비판), `prompt_arg_max_chars`(기본 100,000자)를 넘으면 stdin으로 폴백한다. 두 CLI 모두 `--help`에 명시된 방식이다:
  - Claude Code: `-p`에서 위치 인자 프롬프트를 생략하면 stdin을 프롬프트로 읽는다.
  - Codex: 프롬프트 자리에 `-`를 주면 stdin에서 읽는다.
- **Claude 는 프롬프트 앞에 `--` 가 필수**: `--allowedTools <tools...>` 가 공백 구분 가변 인자라서 뒤따르는 프롬프트를 도구 이름으로 삼킨다(첫 실제 실행에서 "Input must be provided..." 로 발견). `--` 를 넣으면 파싱을 통과함을 잘못된 API 키 + `--bare` 로 확인(인증 단계에서 실패하므로 사용량 소모 없음). JSON 의 `is_error: true` 는 exit 0 이어도 실패로 본다.
- `--help` 검증에서 확인한 추가 사실: Claude의 `--permission-mode`는 `acceptEdits|auto|bypassPermissions|manual|dontAsk|plan`, Codex의 `--sandbox`는 `read-only|workspace-write|danger-full-access`. 표의 값은 모두 유효하다.
- 명령어의 고정 부분(`-p --output-format json`, `exec --skip-git-repo-check`)도 `base_args`로 설정에 노출해 버전 차이에 대응한다.
- **한도 감지**: stderr/stdout에서 rate limit, usage limit 류 문구를 정규식으로 감지 → `rate_limited=True`. Orchestrator는 상태 저장 후 "한도 도달, 나중에 `duet resume`" 안내하며 종료(자동 대기는 하지 않음).

### 5.3 판정 형식

리뷰 프롬프트는 응답 마지막에 아래 블록을 요구한다.

```
<verdict>
status: APPROVED | CHANGES_REQUESTED
must_fix: 3
</verdict>
```

- 파싱 실패 시 레거시 형식 `VERDICT: APPROVED` 한 줄도 허용.
- 둘 다 없으면 `CHANGES_REQUESTED`로 간주하되, Transcript에 `parse_failed` 표시.
- `status: APPROVED`인데 `must_fix > 0`이면 모순 → `CHANGES_REQUESTED`로 처리.

### 5.4 Orchestrator 흐름

```
check() 두 어댑터
DebatePhase (skip-design 아니면)
  propose(A), propose(B)
  for r in 1..debate_rounds: critique(A←B), critique(B←A)  # 각자 개정안 반환
  synthesize(synth) → workdir/DESIGN.md
  (design-only면 종료)
BuildPhase
  workspace.ensure_repo(); base = commit("duet: design")
  loop i in 1..max_review:
    implementer.ask(implement 또는 fix)          # WRITE
    commit("duet: impl round i")
    diff = workspace.diff(base, HEAD, exclude=[DESIGN.md])
    reviewer.ask(review)                          # READ
    if workspace.dirty(): 경고 + 되돌림
    verdict → APPROVED면 종료
  미승인 종료 시 마지막 리뷰 경로 안내
```

- 각 스텝 직후 `RunState`를 갱신 저장. resume은 마지막 완료 스텝 다음부터 이어간다.
- `done_unapproved`로 끝난 실행은 `resume --max-review N`(N > 기존 상한)으로만 이어갈 수 있다. 이때 다음 라운드는 마지막 리뷰를 반영하는 `fix`로 시작한다. 상한을 늘리지 않으면 안내 메시지와 함께 거부한다.
- 같은 에이전트가 두 번 연속 실패(비정상 종료)하면 1회 재시도 후 상태 저장하고 종료.

---

## 6. 기록과 상태

```
<workdir>/.duet/
└── runs/
    └── 20261014-174138/
        ├── run.json            # RunState (아래)
        ├── 01_propose_claude.md
        ├── 02_propose_codex.md
        ├── 03_r1_critique_claude.md
        ├── ...
        └── 09_review2_codex.md
```

- `.duet/`는 자동으로 `.gitignore`에 추가.
- 각 기록 파일 상단에 메타데이터 주석(에이전트, 모드, 소요 시간, exit code)을 넣는다.
- 실패한 호출도 `NN_label_failed.md` 로 남긴다(stderr 포함).
- `done` 은 완료한 스텝 키 목록. resume 은 이 목록에 없는 스텝부터 실행하며, 필요한 텍스트는 기록 파일에서 다시 읽는다.
- `done_design` 은 `--design-only` 로 설계만 끝낸 상태(끝난 실행이므로 resume 불가).

```json
{
  "run_id": "20261014-174138",
  "task": "...",
  "config": { "implementer": "claude", "reviewer": "codex", "synth": "codex",
              "debate_rounds": 1, "max_review": 3 },
  "phase": "build",
  "step": "review",
  "round": 2,
  "base_commit": "5da7bc7",
  "proposals": { "claude": "01_propose_claude.md", "codex": "02_propose_codex.md" },
  "last_review": "07_review1_codex.md",
  "status": "running | done_approved | done_unapproved | done_design | stopped_rate_limit | failed",
  "done": ["propose:claude", "propose:codex", "critique:1:claude", "..."],
  "calls": [ { "agent": "claude", "step": "propose", "sec": 41.2, "exit": 0 } ]
}
```

---

## 7. 프롬프트 템플릿

- `src/duet/templates/*.md`에 둔다. `{task}`, `{own}`, `{other}`, `{other_name}`, `{diff}`, `{review}` 등 `str.format` 플레이스홀더 사용.
- 사용자가 `<workdir>/.duet/templates/`에 같은 이름의 파일을 두면 그걸 우선 사용(커스터마이즈).
- 초기 문구는 `prototype/agent_team.py`의 `P_*` 상수를 기반으로 하되, 판정 블록을 5.3 형식으로 바꾼다.
- 비판 프롬프트의 개정안 추출은 `## 개정안` 헤더 기준. 없으면 응답 전체를 개정안으로 사용.

---

## 8. 설정

우선순위: CLI 인자 > `<workdir>/duet.toml` > 기본값

```toml
implementer = "claude"
reviewer = "codex"
synth = "codex"           # 생략 시 reviewer
debate_rounds = 1
max_review = 3
timeout_sec = 1200
max_diff_chars = 60000

prompt_arg_max_chars = 100000   # 넘으면 stdin 폴백

[claude]
bin = "claude"
base_args = ["-p", "--output-format", "json"]
read_args = ["--allowedTools", "Read,Glob,Grep"]
write_args = ["--permission-mode", "acceptEdits", "--allowedTools", "Read,Edit,Write,Glob,Grep,Bash"]

[codex]
bin = "codex"
base_args = ["exec", "--skip-git-repo-check"]
read_args = ["--sandbox", "read-only"]
write_args = ["--sandbox", "workspace-write"]
```

- 범위를 벗어난 값(`debate_rounds` 0~5, `max_review` 1~10, implementer == reviewer 등)은 조용히 보정하지 않고 에러로 거부한다.

`tomllib`(3.11+ 표준 라이브러리)로 읽는다.

---

## 9. 안전장치

- **작업 폴더 가드**: workdir이 홈 디렉터리 자체이거나 `/`이면 거부. 기존 git 저장소인데 커밋 안 된 변경이 있으면 거부(`--force`로 무시 가능).
- **반복 상한**: `debate_rounds`, `max_review` 상한을 각각 5, 10으로 강제.
- **리뷰어 쓰기 차단**: READ 모드 + 리뷰 후 `git status` 검사 → 변경 있으면 경고 후 `checkout`/`clean`으로 되돌림(`.duet/` 제외).
- **타임아웃**: 호출별 `timeout_sec`. 초과 시 프로세스 종료 후 실패 처리.
- **한도 도달**: 상태 저장 후 정상 종료, resume 안내.

---

## 10. 테스트 전략

- **실제 claude/codex를 테스트에서 절대 호출하지 않는다.**
- `tests/fake_bin/claude`, `tests/fake_bin/codex`: 받은 인자를 JSON 파일로 덤프하고, 환경변수로 지정한 시나리오에 따라 정해진 응답을 출력하는 가짜 실행 파일. 테스트에서 `PATH` 앞에 끼워 넣거나 config의 `bin`을 이 경로로 지정.
  - 이걸로 검증: 명령어 조립(모드별 플래그), 출력 파싱(JSON / last-message 파일), 비정상 종료, 한도 문구 감지, 타임아웃.
- `MockAdapter`: Phase/Orchestrator 단위 테스트용. 시나리오(예: "첫 리뷰 반려, 두 번째 승인")를 생성자로 주입.
- e2e(mock): 임시 디렉터리에서 `duet run --mock` 전체 실행 → 기록 파일 순서, 커밋 수, 최종 status 검증. 중간에 강제 실패시킨 뒤 `duet resume`으로 완주하는 시나리오 포함.

---

## 11. 구현 마일스톤

각 마일스톤은 **완료 기준을 모두 통과하고 커밋한 뒤** 다음으로 넘어간다.

### M0. 뼈대
- `pyproject.toml`(엔트리포인트 `duet`), 패키지 구조, `duet --help`, pytest 동작
- ✅ `pip install -e .` 후 `duet --help` 출력, `pytest` 통과(빈 테스트라도)

### M1. 실행부 + 어댑터
- `runner.py`, `agents/base.py`, `claude_code.py`, `codex.py`, `mock.py`, `config.py`
- **실제 CLI 검증 단계**: 사용자 PC에 claude/codex가 있으면 `claude --help`, `codex exec --help`를 실행해 5.2 표의 플래그가 맞는지 확인하고, 다르면 기본값을 수정 후 DESIGN.md 5.2를 갱신. (실제 프롬프트 호출은 하지 말 것 — 사용자 구독 한도 소모)
- ✅ fake_bin 기반 테스트로 모드별 명령어, 파싱, 에러, 한도 감지, 타임아웃 검증

### M2. 판정 + 기록 + 상태
- `verdict.py`, `transcript.py`, `state.py`
- ✅ 판정 파싱 테스트(정상/레거시/누락/모순), RunState 저장·로드 왕복 테스트

### M3. 설계 토론 단계
- `prompts.py` + 템플릿, `phases/debate.py`
- ✅ MockAdapter로 라운드 0/1/2 각각 기록 파일 개수·순서, DESIGN.md 생성 검증

### M4. 구현 + 교차 리뷰 단계
- `workspace.py`, `phases/build.py`
- ✅ 승인/미승인/리뷰어가 파일 수정한 경우(되돌림)/diff 잘림 테스트

### M5. Orchestrator + CLI 완성
- `run`, `resume`, `log` 서브커맨드, 작업 폴더 가드, 설정 우선순위
- ✅ e2e mock 테스트(완주, 중단 후 resume), `duet run ... --mock` 수동 실행 시 진행 로그가 보기 좋게 출력

### M6. 마무리
- README(설치, 로그인 전제, 사용 예, 커스텀 템플릿, 주의사항)
- ✅ 사용자가 실제 CLI로 `--design-only` 한 번 돌려볼 수 있는 상태

---

## 12. 리스크와 미결 사항

| 리스크 | 대응 |
|---|---|
| CLI 플래그가 버전마다 다름 | 플래그를 설정으로 분리, M1에서 `--help`로 검증 |
| 구독 사용량 한도 | 반복 상한, 한도 감지 후 중단·resume |
| 긴 프롬프트가 인자 길이 초과 | stdin/파일 폴백 (M1에서 각 CLI 지원 방식 확인) |
| 모델이 판정 형식을 안 지킴 | 레거시 형식 허용, 실패 시 반려로 간주 + 기록 |
| 둘이 끝없이 반려 핑퐁 | `max_review` 상한, 구현자 반론을 `IMPLEMENTATION_NOTES.md`에 남기게 해 리뷰어가 참고 |
| 약관 | 공식 CLI를 본인 PC에서 개인 용도로만 사용. 웹 자동화 금지 |

**미결 (v2 후보)**: 사람 개입 모드(라운드마다 승인 받기), 리뷰어 2명(둘 다 리뷰), 토론 요약 리포트 HTML, 3번째 모델 추가.
