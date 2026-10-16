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
- 외부에 공개하는 웹 서비스, 데이터베이스 (관리자 UI 는 본인 PC 의 127.0.0.1 전용 — 13장)
- 유료 API 직접 호출 (Anthropic/OpenAI SDK 사용 안 함)
- chatgpt.com / claude.ai 웹 화면 자동화 (약관 위험 + 취약)
- 병렬 실행 (v2 후보로만 남김). 역할은 워크플로 템플릿(19장)으로 여럿 둘 수 있지만 호출은 한 번에 하나씩 순차로 한다.
- Claude Code·Codex 외의 CLI (역할은 둘 중 하나의 CLI 에 모델·강도·지시를 붙인 것)

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

# 관리자 UI (브라우저로 보기 + 실행 제어)
duet ui
```

실행 중 터미널에는 단계별 진행 상황(누가 무엇을 하는 중인지, 소요 시간, 판정)이 한 줄씩 찍힌다.

종료 코드: 0 승인 완료/설계만 완료, 1 미승인 종료, 2 사용 오류, 3 중단(한도·반복 실패 → `resume`), 130 사용자 중단(Ctrl-C 또는 SIGTERM → `resume`).

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
- 프롬프트가 매우 길어질 수 있으므로(설계안 2개 + 비판), `prompt_arg_max_bytes`(기본 100,000 바이트, UTF-8 기준)를 넘으면 stdin으로 폴백한다. Linux 의 인자 하나 한도는 128KiB 이고 한글은 글자당 3바이트라 글자 수로 재면 안 된다. 두 CLI 모두 `--help`에 명시된 방식이다:
  - Claude Code: `-p`에서 위치 인자 프롬프트를 생략하면 stdin을 프롬프트로 읽는다.
  - Codex: 프롬프트 자리에 `-`를 주면 stdin에서 읽는다.
- **Claude 는 프롬프트 앞에 `--` 가 필수**: `--allowedTools <tools...>` 가 공백 구분 가변 인자라서 뒤따르는 프롬프트를 도구 이름으로 삼킨다(첫 실제 실행에서 "Input must be provided..." 로 발견). `--` 를 넣으면 파싱을 통과함을 잘못된 API 키 + `--bare` 로 확인(인증 단계에서 실패하므로 사용량 소모 없음). JSON 의 `is_error: true` 는 exit 0 이어도 실패로 본다.
- `--help` 검증에서 확인한 추가 사실: Claude의 `--permission-mode`는 `acceptEdits|auto|bypassPermissions|manual|dontAsk|plan`, Codex의 `--sandbox`는 `read-only|workspace-write|danger-full-access`. 표의 값은 모두 유효하다.
- 명령어의 고정 부분(`-p --output-format json`, `exec --skip-git-repo-check`)도 `base_args`로 설정에 노출해 버전 차이에 대응한다.
- **한도 감지**: rate limit, usage limit 류 문구를 정규식으로 감지 → `rate_limited=True`. Orchestrator는 상태 저장 후 "한도 도달, 나중에 `duet resume`" 안내하며 종료(자동 대기는 하지 않음).
  - 호출이 **실패**했을 때만 stderr/stdout 끝부분(2000자)과 본문을 검사한다.
  - 호출이 성공했으면 본문이 **400자 이하**일 때만 검사한다(한도 안내문 자체가 응답인 경우). 정상 리뷰가 "rate limit"이나 "429"를 언급했다고 멈추던 오탐을 막는다.

### 5.3 판정 형식

리뷰 프롬프트는 응답 마지막에 아래 블록을 요구한다.

```
<verdict>
status: APPROVED | CHANGES_REQUESTED
must_fix: 3
</verdict>
```

- 파싱 실패 시 레거시 형식 `VERDICT: APPROVED` 한 줄도 허용.
- 모델이 붙이는 마크다운 장식(`**status:** APPROVED`, `` `APPROVED` ``, `- status: ...`)은 무시하고 읽는다.
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
    (리뷰 전 커밋 안 된 변경이 있으면 보존 커밋)
    diff = 변경 파일 요약(stat) + workspace.diff(base, HEAD, exclude=[DESIGN.md, 잠금 파일들])
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

- `.duet/`는 자동으로 `.gitignore`에 추가. `.gitignore` 가 없어서 duet 가 새로 만들 때는 빌드·테스트 부산물(`__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.coverage`, `htmlcov/`, `*.egg-info/`, `.venv/`, `node_modules/`, `.DS_Store`)도 넣는다. 에이전트가 직접 돌린 테스트의 캐시가 구현 커밋에 섞이는 것을 막는다(실제 실행에서 발견). 이미 있는 `.gitignore` 에는 `.duet/` 만 덧붙이고 다른 규칙은 건드리지 않는다.
- 각 기록 파일 상단에 메타데이터 주석(에이전트, 모드, 소요 시간, exit code)을 넣는다.
- 실패한 호출도 `NN_label_failed.md` 로 남긴다(stderr 포함).
- `done` 은 완료한 스텝 키 목록. resume 은 이 목록에 없는 스텝부터 실행하며, 필요한 텍스트는 기록 파일에서 다시 읽는다.
- `done_design` 은 `--design-only` 로 설계만 끝낸 상태(끝난 실행이므로 resume 불가).
- `stopped_user` 는 Ctrl-C 또는 SIGTERM(관리자 UI 의 중지)으로 멈춘 상태. 진행 중이던 호출은 버리고 resume 때 그 스텝부터 다시 한다.
- `console.log`: 터미널에 찍히는 진행 로그를 그대로 run 디렉터리에도 남긴다(UI 가 실시간으로 읽는다).
- `DESIGN.prev.md`: 설계 토론이 기존 `DESIGN.md` 를 덮어쓸 때, 내용이 다르면 원본을 여기 백업한다.
- `<workdir>/.duet/lock.json`: 실행 중인 duet 의 pid 와 run_id. 같은 작업 폴더에서 run/resume 이 동시에 돌지 못하게 막고, 죽은 프로세스가 남긴 잠금은 무시한다.

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
  "status": "running | done_approved | done_unapproved | done_design | stopped_rate_limit | stopped_user | failed",
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
- 개정안·비판 요약은 **성공한** 기록(메타 `ok: true`) 중 같은 (에이전트, 라운드)의 마지막 것을 쓴다. 한도·타임아웃으로 실패한 기록은 exit 0 이어도 쓰지 않는다.

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

prompt_arg_max_bytes = 100000   # UTF-8 바이트. 넘으면 stdin 폴백 (최대 120000)
diff_excludes = ["package-lock.json", "yarn.lock", "uv.lock", "poetry.lock", "Cargo.lock", "go.sum", "..."]  # 리뷰 diff 에서 뺄 파일

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
effort = "medium"                                         # 18장
step_effort = { synthesize = "high", review = "high" }

# 에이전트·테스트 자식 프로세스에서 뺄 환경 변수(glob)와 예외 (18장)
env_strip = ["ANTHROPIC_API_KEY", "*_API_KEY", "*_TOKEN", "..."]
env_keep = ["CLAUDE_CODE_OAUTH_TOKEN"]
```

- 범위를 벗어난 값(`debate_rounds` 0~5, `max_review` 1~10, implementer == reviewer 등)은 조용히 보정하지 않고 에러로 거부한다.

`tomllib`(3.11+ 표준 라이브러리)로 읽는다.

---

## 9. 안전장치

- **작업 폴더 가드**: workdir이 홈 디렉터리 자체이거나 `/`이면 거부. 기존 git 저장소인데 커밋 안 된 변경이 있으면 거부(`--force`로 무시 가능). 단 `.duet/` 아래 변경은 항상 무시하고, `--skip-design` 일 때는 `DESIGN.md` 변경도 무시한다(설계만 → 사람이 수정 → 구현 흐름).
- **프로세스 정리**: claude/codex 는 새 프로세스 그룹으로 띄우고, 타임아웃·중단 시 그룹 전체를 SIGTERM → SIGKILL 한다. 에이전트가 띄운 테스트나 셸 명령이 남지 않는다. 출력 파이프가 닫히기가 아니라 **프로세스 종료**를 기다리므로, 백그라운드 프로세스가 파이프를 물고 있어도 정상 종료한 호출이 타임아웃으로 처리되지 않는다(2초 유예 후 그룹 정리).
- **git 오류**: 에이전트가 하위 저장소를 만들었거나 커밋이 실패하면 `failed` 로 저장하고 안내 후 종료. 구현 호출이 성공한 뒤 커밋 전에 실패하면 `impl:i:called` 가 남아 resume 때 구현을 다시 부르지 않는다. duet 커밋은 `commit.gpgsign=false` 로 한다.
- **resume 때 사용자 수정 보존**: 리뷰 직전에 커밋 안 된 변경이 있으면 'duet: uncommitted changes before review i' 로 커밋한 뒤 리뷰한다(리뷰어가 바꾼 것으로 오인해 지우지 않음).
- **동시 실행 방지**: `.duet/lock.json` 잠금.
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

### M8. 설정·모델·사용량·환경 점검 (2026-10-15 사용자 요청으로 추가)
- `settings.py`, `usage.py`, `doctor.py`, `ui/terminal.py`, `duet doctor`, `--claude-model` 등
- ✅ 설정 층 우선순위, 모델 플래그, 사용량 수집(가짜 CLI·가짜 세션 기록), 점검, pty 터미널 입력 테스트

### M9. 원격 머신 (2026-10-15 사용자 요청으로 추가)
- `remote.py`(duet.pyz 배포, ssh, `duet _api`), 작업 기록 파일화(`duet _job`)
- ✅ 가짜 ssh 로 배포 → 원격 mock 실행 → 원격 기록 조회까지, 헤드리스 브라우저로 화면 확인

### M10. 반려 핑퐁 방지 + duet 테스트 (2026-10-15 사용자 요청으로 추가)
- `policy.py`(승인 판단·수렴 감지), `testing.py`(테스트 명령 결정·실행), 리뷰·수정·구현 템플릿 개정
- ✅ 심각도 판정·수렴 감지·테스트 상태 단위 테스트, build 단계 통합(테스트 실패 시 승인 보류, 부산물 정리, duet.toml 명령, 이전 리뷰 전달, 수렴 안 됨 → resume)

### M11. 리뷰 효율 + 재현 테스트 + 실시간 보기 (2026-10-15 사용자 요청으로 추가)
- 증분 리뷰 diff, 테스트 재실행 안내, `repro.py`, `activity.py`, UI 실시간 작업 보기
- ✅ 재현 테스트 파싱·흐름, 증분 diff(예전 실행 대비), 두 CLI 세션 기록 파싱, 헤드리스 브라우저 확인

### M12. 단계별 추론 강도 + 자식 환경 변수 정리 (2026-10-15 사용자 요청으로 추가)
- `AgentConfig.step_effort`, `--{agent}-step-effort`, Codex 기본 `medium`(종합·첫 리뷰 `high`), `env_strip`/`env_keep`, `doctor` 의 API 키 점검 (18장)
- ✅ 단계·라운드별 effort 결정, 설정 층 규칙(effort 만 정한 층은 단계별을 비움), resume 보존·예전 run 호환, 가짜 CLI 로 단계별 플래그와 자식 환경(비밀 변수 제거·keep 예외·테스트 명령) 검증

### M13. 워크플로 템플릿 (2026-10-16 사용자 요청으로 추가)
- `workflow.py`(역할·단계 정의, 로드·검증, classic), 내장 템플릿 `workflows/*.toml`, 단계 종류 explore/debate/build/audit, 리뷰어 여러 명, 역할별 지시·프롬프트, `--workflow`, `duet workflows`, UI 선택 (19장)
- ✅ 템플릿 검증 오류, classic 이 예전과 같은 기록·커밋을 남김, 역할별 모델·강도 플래그, 리뷰어 2명 판정 합산·수정 프롬프트, explore/audit, resume 시 저장된 정의 사용, UI 목록·실행

### M14. 벤치마크 (2026-10-16 사용자 요청으로 추가)
- `bench.py`, 내장 과제 묶음 `bench_suites/basic/`(숨은 수용 테스트 포함), `duet bench run|report|list` (20장)
- ✅ 숨은 테스트가 참조 구현에서 모두 통과(과제 묶음 자체의 검증), mock 으로 실행 → 숨은 테스트 채점 → results.json·요약표, 실제 실행은 `--yes` 없이는 거부

### M15. 리뷰 비용 줄이기 (2026-10-16 사용자 요청으로 추가)
- 리뷰 패킷(함수 단위 문맥 diff, 바뀐 함수의 호출부, duet 테스트 결과, 재열람 자제 안내), JSON 판정(`--json-schema`/`--output-schema`), 2라운드부터 리뷰어 세션 재사용(21장)
- ✅ 패킷 생성(호출부·문맥 diff·크기 제한), 스키마 플래그·구조화 결과 → 기존 판정·재현 테스트 형식 변환, 세션 이어가기 플래그·실패 시 새 세션 폴백·재사용 상한, Codex 이어간 세션의 사용량 차이 계산, 설정으로 끌 수 있음. 효과는 hard 벤치마크로 측정

### M7. 관리자 UI (2026-10-15 사용자 요청으로 추가)
- `registry.py`, `lock.py`, `ui/dashboard.py`, `ui/server.py`, `ui/static/*`, `duet ui`
- ✅ HTTP 수준 테스트(토큰·Host 검사, 경로 조작 거부, 조회, 실행·중지·이어하기), 헤드리스 브라우저로 화면·JS 오류 확인

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

---

## 13. 관리자 UI (`duet ui`)

본인이 여러 작업 폴더의 실행을 한눈에 보고, 브라우저에서 시작·중지·이어하기를 하기 위한 로컬 웹 대시보드.

```
duet ui [--port 8787] [--host 127.0.0.1] [--workdir PATH ...] [--no-browser]
```

### 구성
- **프로젝트 목록**: `$DUET_HOME/projects.json`(기본 `~/.duet`). `duet run`/`resume` 이 작업 폴더를 자동 등록하고, UI 에서 경로를 추가·제거(목록에서만)할 수 있다.
- **서버**: 표준 라이브러리 `http.server`(ThreadingHTTPServer) + JSON API. 화면은 의존성 없는 HTML/CSS/JS 한 벌(`ui/static`).
- **실행 제어**: UI 는 `python -m duet run|resume ...` 를 백그라운드 프로세스(새 세션)로 띄운다. 과제는 `<workdir>/.duet/ui/tasks/*.md` 에, 프로세스 출력은 `.duet/ui/jobs/*.log` 에 남는다. UI 를 꺼도 실행은 계속된다.
- **중지**: `.duet/lock.json` 의 pid 에 SIGTERM → duet 가 `stopped_user` 로 저장하고 진행 중이던 호출의 프로세스 그룹을 정리한다.
- **실시간**: 실행 중이면 2초마다 폴링. `console.log` 를 이어 읽고, 마지막 "실행 중" 줄로 지금 호출과 경과 시간을 보여준다.

### 화면
| 화면 | 내용 |
|---|---|
| 프로젝트 | 프로젝트 카드(최근 상태, 실행 중 표시), 경로 추가, UI 가 시작한 작업의 실패 로그 |
| 프로젝트 상세 | 실행 기록 표, DESIGN.md, 새 실행, 중지 |
| 실행 상세 | 상태·구성·리뷰 이력, 이어하기(미승인이면 리뷰 상한 지정)·중지, 탭: 대화(발언 타임라인 + 마크다운) / 콘솔 / 변경 사항(커밋별 diff, 리뷰어가 받는 diff) / 설계 문서(덮어쓰기 전 백업 포함) |

### UI 서버 업데이트
- 시작할 때 duet 패키지 코드의 해시를 기억하고, `GET /api/server` 로 지금 설치된 코드와 비교한다. 다르면 사이드바에 '업데이트됨 · 다시 시작' 안내를 띄운다(설정 화면에서는 언제든 다시 시작 가능).
- 다시 시작은 같은 포트·같은 토큰으로 자기 자신을 exec 한다(브라우저는 서버가 다시 뜨면 자동 새로고침). duet run 은 별도 프로세스라 계속 돈다. 설치·로그인 같은 터미널 작업이 진행 중이면 거부한다.

### 보안
UI 의 실행 버튼은 셸 권한이 있는 에이전트를 띄우므로, 다른 웹사이트가 브라우저를 통해 이 API 를 부르지 못하게 막는다.
- 기본 바인딩 127.0.0.1. 다른 주소면 시작할 때 경고하고 SSH 터널을 권한다.
- 시작할 때마다 새 토큰. 페이지는 `?t=<토큰>` 이 있어야 열리고, API 는 `X-Duet-Token` 헤더가 맞아야 응답한다(커스텀 헤더라 교차 출처 요청은 사전 요청에서 막힌다).
- 루프백 바인딩이면 Host 헤더가 `127.0.0.1:포트`/`localhost:포트` 인지 검사(DNS 리바인딩 방지).
- CSP `script-src 'self'`, 인라인 스크립트·스타일 없음, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`.
- 모델 출력(마크다운, diff)은 innerHTML 을 쓰지 않고 DOM 노드로만 그린다. 링크는 http(s) 만 클릭 가능.
- 경로 인자는 등록된 프로젝트, 실제 run 디렉터리, `NN_*.md` 기록 파일, 16진 커밋 해시만 허용.

---

## 14. 설정·모델·사용량·환경 점검

### 전역 설정 `~/.duet/settings.json`
- `workspace_roots`: 새 실행 때 고르는 상위 폴더 목록(첫 번째가 기본). UI 는 "위치 + 폴더 이름"으로 경로를 만든다.
- `defaults`: duet.toml 과 같은 형식의 기본 실행 설정. 우선순위는 **CLI 인자 > `<workdir>/duet.toml` > settings.json defaults > 기본값**. 파일이 깨져 있으면 무시한다.
- `machines`: 원격 머신(15장).

### 모델·추론 강도
- `[claude] model/effort` → `claude --model X --effort Y`, `[codex] model/effort` → `codex exec -m X -c model_reasoning_effort="Y"`. 비우면 각 CLI 의 기본값.
- CLI: `duet run ... --claude-model opus --claude-effort high --codex-model gpt-6.1-sol --codex-effort xhigh`.
- 실행 상태(`run.json` config)에 저장해 resume 때 처음과 같은 모델을 쓴다.
- 단계마다 다른 추론 강도는 `step_effort`(18장). duet 는 Codex 의 기본 강도를 `medium` 으로 명시하므로 `~/.codex/config.toml` 의 `model_reasoning_effort` 보다 우선한다.
- UI 후보: Claude 는 별칭(fable/opus/sonnet/haiku)과 전체 이름, Codex 는 `~/.codex/models_cache.json` 의 모델과 모델별 지원 추론 강도.

### 사용량 (로컬 파일만 읽음, 구독을 쓰지 않음)
- 호출마다 `AgentResult.usage` → 기록 메타(`tokens_in`, `tokens_out`, `cost_usd`, `model`)와 `run.json` calls 에 저장.
  - Claude: `-p --output-format json` 응답의 usage·total_cost_usd·modelUsage.
  - Codex: 호출 직후 `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` 중 같은 작업 폴더·시작 시각 이후의 세션에서 token_count(누적 토큰)와 rate_limits.
- 구독 한도: Codex 는 최근 세션 기록의 rate_limits(창별 사용률 %, 초기화 시각, 플랜). Claude CLI 는 한도(%)를 노출하지 않으므로 `~/.claude/projects/*.jsonl` 의 메시지 사용량을 합산해 최근 5시간·7일 토큰만 보여준다.
- UI '사용량' 화면: Codex 한도 막대, Claude 토큰, duet 실행의 에이전트별·날짜별·프로젝트별 합계. 실행 화면에는 에이전트별 토큰과 Codex 한도 70% 이상 경고.

### 환경 점검과 설치·로그인
- `duet doctor [--json]`: duet/Python, git, curl, uv, Claude Code(설치·`claude auth status`), Codex CLI(설치·`codex login status`).
- UI '환경·로그인' 화면의 버튼은 **고정된 동작만** 실행한다(임의 명령 없음):
  - 설치: `curl -fsSL https://claude.ai/install.sh | bash`, `curl -fsSL https://chatgpt.com/codex/install.sh | sh`, `curl -LsSf https://astral.sh/uv/install.sh | sh`, `uv python install 3.12`, git/curl 은 시스템 패키지 관리자(sudo).
  - 로그인: `claude auth login`, `codex login --device-auth`. 로그아웃도 제공.
- 동작은 가상 터미널(pty)에서 돌고, UI 가 출력(제어 문자 제거)을 보여주며 링크를 뽑아 주고, 입력칸으로 코드·sudo 비밀번호(숨김)를 보낼 수 있다.
- 설치 스크립트가 `~/.local/bin` 에 두므로 duet 는 자식 프로세스 PATH 끝에 `~/.local/bin`, `~/.duet/bin` 을 덧붙인다(사용자 PATH 우선).

## 15. 원격 머신

- 설정의 머신: `{id, name, ssh: "user@host", port, workspace_root, python}`. SSH 는 **키 인증만**(BatchMode), ControlMaster 로 연결 재사용.
- 원격에는 Python 3.11+ 만 필요하다. UI 의 '배포'가 설치된 duet 패키지로 실행 가능한 zip(`duet.pyz`, 내용 해시로 버전 비교)을 만들어 `~/.duet/bin/` 에 복사하고 `~/.duet/bin/duet` 래퍼를 만든다. Python 이 없으면 uv → Python 3.12 설치 버튼으로 준비한다.
- 원격 조회·동작은 `ssh <머신> <python> ~/.duet/bin/duet.pyz _api <메서드>` (인자·결과 JSON). 로컬 HTTP API 와 같은 메서드 표를 쓴다. 원격 실행 기록·프로젝트 목록은 원격 머신의 `.duet/`, `~/.duet/` 에 남는다.
- UI 는 모든 화면·주소가 머신을 구분한다(`#/m/<id>/p/<경로>/r/<run>`). 프로젝트 목록은 머신별로 묶고, 원격 목록은 8초 캐시.
- 설치·로그인 동작은 `ssh -tt <머신> '<명령>'` 으로 같은 터미널 화면에서 한다.
- UI 가 시작한 작업은 `~/.duet/jobs/*.json` 에 기록하고, `duet _job` 래퍼가 끝날 때 종료 코드를 `.rc` 에 남긴다(UI 를 다시 켜거나 원격에서도 결과를 안다).

---

## 16. 반려 핑퐁 방지와 duet 테스트

memo-cli 실험에서 리뷰 4라운드가 모두 반려됐다(반드시 고칠 것 3 → 1 → 2 → 1). 구현자가 지적된 예외만 좁게 막고, 리뷰어가 매번 더 극단적인 입력을 새로 찾았다. 또 리뷰어는 읽기 전용이라 파일을 만드는 테스트를 돌리지 못했다.

### 테스트 단계 (build: impl 커밋 → **test** → review)
- 명령 결정: 명시값(`--test-command`, 설정의 `test_command`, "auto" 가 아닌 것) → 작업 폴더 `duet.toml` 의 `test_command`(구현 프롬프트가 구현자에게 적게 한다) → 자동 감지(pyproject/setup.py + tests → `uv run pytest -q`(uv.lock 있을 때) 또는 `python3 -m pytest -q`, package.json test 스크립트 → `npm test --silent`, Cargo → `cargo test --quiet`, go.mod → `go test ./...`, Makefile test → `make test`). `none` 이면 끔.
- 결과 상태: passed / failed / timeout / error(명령 없음 126·127, pytest 수집 0개=5). 기록 `NN_test{i}.md`(agent: duet), `run.json` 의 `tests[i]`.
- 테스트가 만든 부산물은 커밋하지 않는다(테스트 후 작업 트리를 커밋 상태로 되돌림).
- 결과는 리뷰 프롬프트와 다음 수정 프롬프트에 들어간다. `require_tests_pass`(기본 true)면 failed/timeout 일 때 리뷰어가 승인해도 승인하지 않는다. error 는 환경 문제일 수 있어 막지 않는다.

### 심각도와 승인 판단 (`policy.decide`)
- 리뷰 템플릿: 지적마다 [P1] 핵심 동작·데이터 손실·보안·테스트 실패, [P2] 설계 위반·일반 입력 오류, [P3] 드문 입력·극단적 경계 사례·취향. 판정 블록에 `p1/p2/p3` 개수.
- 막는 지적 수 = `block_severity`(기본 P2) 이하 심각도 개수의 합. 심각도가 있으면 duet 가 이 수로 판단한다(0 이면 리뷰어가 반려해도 승인, 0 이 아니면 리뷰어가 승인해도 반려). 심각도가 없으면 예전 규칙(must_fix, 모순 처리).
- 리뷰어에게 이전 리뷰의 '반드시 고칠 것'을 보여주고, 해결 여부를 먼저 확인하게 하며 새 지적에는 [새] 를 붙이게 한다.
- `run.json` 의 `review_history`: 라운드별 리뷰어 판정, duet 판단, 막는 지적 수, 심각도, 테스트 상태, 이유.

### 수렴 실패 감지 (`policy.stalled`)
- 막는 지적 수가 `stall_rounds`(기본 2) 라운드 연속으로 그 전까지의 최저치보다 낮아지지 않으면 멈춘다: `done_unapproved`, `stop_reason: "stalled"`. 상한까지 가서 멈추면 `stop_reason: "max_review"`.
- 수렴 안 됨으로 일찍 멈춘 실행은 `--max-review` 없이 resume 할 수 있고, 이때 수렴 판단은 그 라운드부터 다시 센다(`stall_baseline_round`).

### 설정
`test_command = "auto"`, `test_timeout_sec = 600`, `require_tests_pass = true`, `block_severity = "P2"`, `stall_rounds = 2`. CLI: `--test-command`, `--block-severity`, `--stall-rounds`. 실행 상태에 저장해 resume 때 같은 규칙을 쓴다. UI 의 새 실행 창·설정 화면에서도 고른다.

---

## 17. 리뷰 효율, 재현 테스트, 실시간 작업 보기

### 리뷰 토큰
memo-cli 실측(Codex 세션 기록): 설계 단계 호출은 입력 약 2만 토큰인데 리뷰는 28만~39만 토큰이었다. 리뷰 프롬프트(diff 6만 자)가 리뷰어의 도구 호출마다 다시 입력되기 때문이다.
- `review_diff = "incremental"`(기본): 2라운드부터 지난 리뷰 시점 커밋(`reviewed_commits[i]`, 없으면 'duet: impl round i' 커밋) 이후의 diff 만 넣고, 처음부터의 변경은 파일 요약(stat)만 준다. `full` 이면 매번 전체.
- duet 가 테스트를 돌린 라운드에는 리뷰어에게 "전체 테스트를 다시 돌리지 마라, 필요한 것만 좁게"라고 안내한다.

### 재현 테스트 (`repro_tests = true`)
- 리뷰어는 지적을 `<repro path="tests/test_repro_x.py">…</repro>` 로 낼 수 있다. duet 가 검증(작업 폴더 안 상대 경로, 이름이나 폴더에 test/spec, 새 파일만, 최대 5개·20KB)해 저장하고 'duet: repro tests from review i' 로 커밋한 뒤 테스트 명령을 돌린다.
- 결과: failed = 재현됨(지적이 맞음), passed = 재현 안 됨. 기록 `NN_repro{i}.md`, `run.json` 의 `repros[i]`.
- 다음 수정 프롬프트에 파일 목록과 재현 여부를 넣고, 통과시키게 한다(테스트가 틀렸다면 고치고 이유를 IMPLEMENTATION_NOTES.md 에). 다음 라운드의 duet 테스트에 자연히 포함된다.

### 실시간 작업 보기
- 호출 방식은 그대로 두고, 두 CLI 가 실시간으로 쓰는 세션 기록을 읽는다(`activity.py`). Claude: `~/.claude/projects/<cwd 의 영숫자 외 문자를 '-' 로>/*.jsonl`(없으면 최근 기록 중 cwd 일치), Codex: 세션 기록 중 cwd 일치. 지금 호출 시작 이후의 파일 읽기·수정·명령·검색·메시지를 뽑는다.
- `GET /api/activity` (원격 머신도 같은 API). UI 는 실행 중이면 타임라인의 '진행 중' 항목을 자동으로 열어 2초마다 갱신한다.


---

## 18. 단계별 추론 강도와 자식 환경 변수

근거: `reports/AI 에이전트 오케스트레이션 고급 조사.md`(로컬 조사 보고서) 개선 후보 1·2번. Codex 요금표에서 출력(추론 포함)은 미캐시 입력의 5배, 캐시 입력의 50배 요율이라, 모든 단계를 xhigh 로 도는 것이 가장 큰 회피 가능 비용이다. OpenAI 가이드는 medium 을 일상 기본으로 둔다. 또 `claude -p` 는 `ANTHROPIC_API_KEY` 가 있으면 구독 대신 API 과금으로 조용히 바뀐다.

### 18.1 단계별 추론 강도 (`step_effort`)
- `[claude]`·`[codex]` 에 `step_effort = { 단계 = 강도 }`. 단계 키: `propose`, `critique`, `synthesize`, `implement`, `fix`, `review`(1라운드 리뷰), `rereview`(2라운드부터의 리뷰).
- 호출의 강도 = `step_effort[단계]` → 없으면 `effort` → 비어 있으면 강도 플래그를 붙이지 않음(CLI 기본값). 키마다 독립이다(`rereview` 가 없으면 `review` 가 아니라 `effort` 로 간다).
- 기본값: Codex `effort = "medium"`, `step_effort = { synthesize = "high", review = "high" }`. 즉 설계 종합과 첫 리뷰만 high, 증분 재리뷰와 나머지는 medium, xhigh 는 사용자가 고를 때만. Claude 는 비워 둔다(CLI 기본값).
- **층 규칙**: 한 설정 층(전역 설정 defaults, `duet.toml`, CLI 인자)이 `effort` 만 정하고 `step_effort` 를 정하지 않으면 그 층이 `step_effort` 를 비운다 = "모든 단계 같은 강도". 둘 다 정하면 둘 다 적용한다. `step_effort` 는 층마다 통째로 바뀐다(키 단위 병합 안 함).
  - 그래서 `--codex-effort xhigh` 는 예전처럼 모든 단계 xhigh, `effort = ""` 는 예전처럼 CLI 기본값(`~/.codex/config.toml`)을 쓴다.
- CLI: `--{agent}-step-effort review=high,fix=low` (같은 실행에 `--{agent}-effort` 를 함께 주면 나머지 단계는 그 값).
- `run.json` config 에 `{agent}.step_effort` 를 저장해 resume 때 같은 규칙을 쓴다. 이 키가 없는 예전 실행은 저장된 단일 `effort` 로 모든 단계를 돈다(예전과 같음).
- 기록 메타와 사용량의 `effort` 는 그 호출에 실제로 쓴 값. 시작 로그: `codex gpt-6.1-sol(medium; synthesize·review=high)`.
- UI: 새 실행 창의 추론 '기본값(단계별)'은 아무 플래그도 넘기지 않아 단계별 기본이 유지된다. 값을 고르면 모든 단계 그 값.

### 18.2 자식 프로세스 환경 변수 (`env_strip`, `env_keep`)
- claude/codex 호출과 duet 가 돌리는 테스트 명령의 자식 프로세스에서, 이름이 `env_strip`(glob, 대소문자 무시)에 맞는 환경 변수를 뺀다. 단 `env_keep` 에 있는 이름은 남긴다.
  - 기본 `env_strip`: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `OPENAI_API_KEY`, `CODEX_API_KEY`, `*_API_KEY`, `*_TOKEN`, `*_SECRET`, `*_SECRET_*`, `*_PASSWORD`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `GOOGLE_APPLICATION_CREDENTIALS`, `SSH_AUTH_SOCK`.
  - 기본 `env_keep`: `CLAUDE_CODE_OAUTH_TOKEN`(Claude 구독 인증 토큰이라 빼면 로그인이 풀린다).
  - `env_strip = []` 이면 예전처럼 전부 넘긴다.
- git, `doctor`, ssh(원격), UI 가 띄우는 duet 는 그대로 둔다. ssh 는 `SSH_AUTH_SOCK` 이 필요하고, UI 가 띄운 duet 는 자기 자식에게 같은 규칙을 다시 적용한다.
- duet 가 정한 변수(테스트의 `CI=1` 등)는 빼지 않는다. 실행 시작 로그에 뺀 변수 **이름**만 한 줄 남긴다(값은 남기지 않음).
- `duet doctor`: 셸에 `ANTHROPIC_API_KEY`·`ANTHROPIC_AUTH_TOKEN`·`OPENAI_API_KEY`·`CODEX_API_KEY` 가 있으면 경고 항목을 띄운다. duet 설정이 그 변수를 빼면 "duet 는 빼고 넘김(직접 `claude -p` 를 돌리면 API 과금)", 안 빼면 "구독 대신 API 로 과금될 수 있음".

---

## 19. 워크플로 템플릿

미리 정해 둔 **역할군**과 **단계 순서**를 템플릿 파일로 두고 골라 쓴다. 예: "일반 리뷰 + 보안 리뷰", "기존 코드 조사 후 설계", "설계 토론 없이 싸게". 실행은 지금처럼 한 번에 하나씩 순차로 하고, 흐름 제어·resume·종료 판단은 duet 코드가 맡는다(템플릿은 정해진 단계 종류를 조합할 뿐 분기·반복을 직접 쓰지 않는다).

### 19.1 역할 (`[roles.<이름>]`)
| 키 | 뜻 |
|---|---|
| `agent` | `claude` 또는 `codex` (필수) |
| `model`, `effort`, `step_effort` | 이 역할의 모델·추론 강도. 없으면 `[claude]`/`[codex]` 설정(CLI `--codex-model` 등 포함)을 따른다. 층 규칙은 18.1 과 같다(effort 만 쓰면 단계별을 비움) |
| `instructions` | 이 역할의 모든 프롬프트 끝에 붙는 추가 지시 (예: "보안 관점으로만 봐라"). 4000자 이하 |
| `templates` | 단계별 프롬프트 템플릿 교체 `{ review = "review_security" }`. 키는 단계 이름, 값은 템플릿 이름 |

- 이름은 `[a-z][a-z0-9_]{0,23}`. 같은 CLI 를 여러 역할이 써도 된다(예: Claude Opus 설계자 + Claude Sonnet 구현자). bin·args 는 `[claude]`/`[codex]` 설정을 공유한다.
- 기록·로그에는 역할 이름이 보이고(`architect ← propose`), 메타에 `agent`(CLI)와 `role` 을 함께 남긴다. 사용량 합계는 CLI 기준.

### 19.2 단계 (`[[steps]]`, 위에서 아래로 순서대로)
| kind | 키 | 하는 일 | resume 키 |
|---|---|---|---|
| `explore` | `id`, `role` | 읽기 전용으로 기존 코드를 조사(`explore` 템플릿). 결과를 이후 propose·implement 프롬프트 끝에 "사전 조사"로 붙인다 | `explore:<id>` |
| `debate` | `proposers`(1~2), `rounds`, `synth`, `output` | 지금의 설계 토론. 제안자가 1명이면 비판 없이, `synth` 가 없으면 그 제안을 그대로 설계 문서로. `output = "change"` 면 기존 프로젝트의 변경 설계(19.5) | `debate` (+ 기존 세부 키) |
| `build` | `implementer`, `reviewers`(1~3), `max_review` | 지금의 구현·테스트·리뷰 루프. 리뷰어가 여럿이면 아래 19.3 | 기존 키 + `review:i:<역할>` |
| `audit` | `id`, `roles`(1~3) | build 가 승인으로 끝난 뒤, 기준 커밋부터 전체 diff 를 한 번 감사(`audit` 템플릿). **참고용**: 결과는 기록·로그·`run.json` 의 `audits` 에 남고 실행 상태는 바꾸지 않는다. 로그는 `문제 없음` 또는 `확인 필요 — P1=… P2=… P3=… (참고용)` 으로, '반려'라고 쓰지 않는다 | `audit:<id>` |

- 규칙: 단계 1개 이상, `debate`·`build` 는 각각 최대 1개, `debate` 는 `build` 앞, `audit` 은 `build` 뒤, `explore` 는 `build` 앞. `id` 는 같은 kind 안에서 겹치지 않음(기본값 kind 이름). 참조하는 역할은 모두 정의돼 있어야 하고, 한 단계 안에서 역할이 겹치면 안 된다(리뷰어 목록에 구현자 불가).
- `rounds`·`max_review` 를 템플릿에 쓰면 그 값이 duet.toml·전역 설정보다 우선하고, CLI `--debate-rounds`·`--max-review` 가 그보다 우선한다. 정해진 값은 실행 상태에 저장한다.
- `--design-only` 는 debate 단계까지만(앞의 explore 포함), `--skip-design` 은 debate 단계를 건너뛴다.

### 19.3 리뷰어 여러 명
- 같은 라운드에서 리뷰어를 순서대로 부른다(같은 diff, 같은 테스트 결과). 각자 `policy.decide` 로 판단하고, **모두 승인해야 승인**, 막는 지적 수는 합(수렴 판단도 합 기준). 하나라도 판정 블록이 없으면 그 리뷰어는 반려로 본다(기존 규칙).
- 수정 프롬프트에는 모든 리뷰를 `### <역할> 의 리뷰` 로 이어 붙여 넣는다. 각 리뷰어의 '이전 리뷰'는 자기 직전 리뷰다. 재현 테스트는 모든 리뷰에서 모아 한 번에 처리한다.
- `review_history[i]` 의 기존 필드는 합산 값, `reviewers` 에 리뷰어별 판정. `last_reviews` 에 역할 → 마지막 리뷰 파일. 리뷰어가 1명이면 기록·필드가 예전과 같다.

### 19.4 템플릿 파일과 선택
- 위치(앞이 우선): `<workdir>/.duet/workflows/<이름>.toml` → `$DUET_HOME/workflows/<이름>.toml` → 내장(`duet/workflows/`). `--workflow @경로.toml` 로 파일을 직접 줄 수도 있다.
- 최상위 키: `name`(파일 이름과 같지 않아도 됨, 표시용), `description`, `[roles.*]`, `[[steps]]`. 알 수 없는 키는 거부한다.
- 선택: CLI `--workflow 이름`, 설정 `workflow = "이름"`(duet.toml·전역 설정). 기본 `classic`.
- **`classic`** 은 파일이 아니라 설정에서 만든다: 역할 `claude`·`codex`(설정 그대로), `debate(proposers=[claude, codex], synth=synth, rounds=debate_rounds)` → `build(implementer, [reviewer], max_review)`. 기록 이름·resume 키·출력이 M12 와 완전히 같다. `--implementer/--reviewer/--synth` 는 classic 에서만 쓸 수 있다(다른 템플릿과 함께 주면 사용 오류).
- 실행 시작 때 고른 템플릿을 해석한 정의 전체를 `run.json` 의 `workflow` 에 저장하고, resume 은 파일이 아니라 이 저장본을 쓴다. 예전 실행(`workflow` 없음)은 classic.
- 내장 템플릿: `secure`(classic + 보안 리뷰어 + 마지막 감사), `existing`(기존 코드 조사 → 변경 설계 토론(`output = "change"`) → 구현), `lean`(제안자 1명, 토론 없음, 리뷰어 1명. 가장 쌈).
- 프롬프트 템플릿 찾는 곳도 같은 순서로 넓힌다: `<workdir>/.duet/templates/` → `$DUET_HOME/templates/` → 내장. 내장에 `explore.md`, `audit.md`, `review_security.md` 추가. 이름은 `[a-z][a-z0-9_]*`.
- `duet workflows [--workdir P]`: 쓸 수 있는 템플릿 목록(이름, 출처, 설명, 역할·단계 요약). `duet workflows show 이름` 은 해석한 정의를 보여 준다.
- UI: 새 실행 창에 워크플로 선택(설명·역할·단계 미리보기), 실행 상세에 워크플로 이름과 역할 표시. 지금 호출의 실시간 보기는 역할 → CLI 로 바꿔 세션 기록을 찾는다.

### 19.5 기존 프로젝트의 변경 설계 (`output = "change"`)
실제 실행(existing 워크플로)에서 설계 단계가 프로젝트 전체 설계인 DESIGN.md(122줄)를 이번 기능만 다룬 설계(334줄)로 덮어썼다. 설계 단계가 새 프로젝트를 전제로 만들어졌기 때문이다.
- debate 단계에 `output = "change"` 를 주면 설계 결과를 `<workdir>/docs/changes/<run_id>.md` 에 쓰고 **DESIGN.md 는 건드리지 않는다**. 파일은 기준 커밋('duet: design')에 들어간다. 기본값 `output = "design"` 은 예전처럼 DESIGN.md(덮어쓸 때 백업).
- 실행 상태 `design_doc` 에 이 경로(작업 폴더 기준 상대 경로)를 저장해 resume 때도 같은 파일을 쓴다. 없으면 `DESIGN.md`.
- 프롬프트: 구현·수정·리뷰·감사 템플릿은 `DESIGN.md` 대신 `{design_doc}` 를 가리키고, 변경 설계일 때 `{design_note}` 에 "기존 프로젝트의 변경이다. 이번 변경의 설계는 그 파일, 프로젝트 전체 설계(DESIGN.md, 있다면)와 기존 코드 관례를 따르고, 과제에 필요하지 않은 기존 동작은 바꾸지 마라"를 넣는다(새 프로젝트면 빈 줄). 설계안·비판·종합 프롬프트 끝에는 "프로젝트 전체를 다시 설계하지 말고 이번 변경만 설계해라(바꿀 파일·함수, 지킬 기존 동작, 테스트, 문서 갱신)"를 붙인다.
- 구현자가 고치면 안 되는 파일은 `{design_doc}` 이다. 변경 설계에서는 DESIGN.md 가 프로젝트 문서이므로, 변경에 필요하면 구현자가 갱신할 수 있다.
- 리뷰 diff 에서 빼는 파일도 `{design_doc}` (새 프로젝트면 DESIGN.md, 변경 설계면 변경 설계 파일. DESIGN.md 갱신은 리뷰 대상).
- `--design-only` 의 끝 안내와 UI '설계 문서' 탭은 그 실행의 `design_doc` 을 보여 준다.

### 19.6 명령을 실행할 수 없는 리뷰어·감사자
실제 실행에서 Claude 감사자가 "실행 권한이 없어 정적으로만 봤다"고 답했다. Claude 의 읽기 모드는 `--allowedTools Read,Glob,Grep` 이라 명령을 못 돌리는데, 프롬프트는 "필요한 부분만 좁게 확인해라"고 했다. Codex 의 `--sandbox read-only` 는 명령을 돌릴 수 있다.
- 역할이 읽기 모드에서 명령을 실행할 수 있는지: Claude 는 `read_args` 에 `Bash` 가 있을 때만, Codex 는 항상.
- 리뷰의 `{test_instruction}` 과 감사의 `{run_instruction}` 을 이에 맞춘다. 실행할 수 없으면 "너는 이 호출에서 명령을 실행할 수 없다. 코드와 duet 테스트 결과로 판단하고, 실행해 봐야 알 수 있는 의심은 추측으로 반려하지 말고 재현 테스트로 내라(재현 테스트를 끈 실행이면 P3 로)".

### 19.7 테스트 명령의 출처 표시
작업 폴더 `duet.toml` 의 `test_command` 는 설정 층으로도 읽히므로 출처가 `설정` 으로 찍혔다. 설정값이 작업 폴더 `duet.toml` 의 값과 같으면 출처를 `duet.toml` 로 표시한다.

---

## 20. 벤치마크 (`duet bench`)

"두 모델 교차 리뷰가 실제로 나은가", "이 개선이 비용을 줄였나"를 숫자로 답하기 위한 도구. 같은 과제 묶음을 워크플로별로 돌리고, **에이전트가 보지 못한 숨은 수용 테스트**로 결과물을 채점한다.

### 20.1 과제 묶음
```
bench_suites/<묶음>/<과제>/
├── bench.toml     # name, description, kind = "new" | "existing", max_review(선택), timeout_sec(선택)
├── task.md        # 에이전트에게 주는 과제. 숨은 테스트가 부를 인터페이스(패키지 이름, 함수, CLI)를 명시
├── setup/         # (existing) 시작 코드. 작업 폴더에 복사 후 커밋하고 시작
└── hidden/        # 숨은 수용 테스트 (pytest). 실행이 끝난 뒤 채점용 복사본에만 넣는다
```
- 내장 묶음 `basic`(Python, 표준 라이브러리만): 새 프로젝트 4개(`roman` 로마 숫자, `intervals` 구간 병합, `inimini` INI 파서, `textstats` wc 비슷한 CLI) + 기존 프로젝트 1개(`textstats-maxline`: textstats 에 `-L` 추가). 패키지는 작업 폴더 최상위에 둔다(src 레이아웃 아님)고 과제에 적는다.
- 숨은 테스트의 정확성은 duet 저장소의 테스트가 참조 구현(`tests/bench_refs/`)으로 검증한다. 과제 묶음의 버그가 점수를 왜곡하지 않게.
- 사용자 묶음: `--suite <경로>` 로 같은 구조의 폴더를 줄 수 있다.

### 20.2 실행 (`duet bench run`)
```
duet bench run [--suite basic|경로] [--workflow W ...] [--task T ...] [--repeat N] [--max-review N] [--out DIR] [--mock] [--yes]
```
- 과제 × 워크플로 × 반복마다 `<out>/<시각>/<과제>/<워크플로>-<n>/` 에 작업 폴더를 만들고(existing 이면 setup 복사 후 커밋), 같은 프로세스에서 Orchestrator 로 실행한다(순차). 기본 워크플로 `classic`, 기본 out `$DUET_HOME/bench`.
- 실제 실행(`--mock` 아님)은 구독 사용량을 크게 쓰므로, 몇 번 돌지와 예상 호출 수를 보여 주고 `--yes` 가 없으면 시작하지 않는다.
- 한도 도달로 멈춘 실행은 그 자리에서 결과를 `stopped` 로 남기고 다음으로 넘어가지 않고 **벤치마크 전체를 멈춘다**(남은 실행을 돌려 봐야 다 멈춘다). `results.json` 은 실행마다 갱신하므로 중간 결과가 남는다.

### 20.3 채점
- 실행이 끝나면 작업 폴더를 채점용 폴더로 복사(`.git`, `.duet` 제외)하고 `hidden/` 을 `duet_hidden_tests/` 로 넣어 pytest 를 돌린다(`PYTHONPATH=채점 폴더`, 비밀 변수 제거, 시간 제한). pytest 는 `uv` 가 있으면 `uvx pytest`, 없으면 `python3 -m pytest`.
- 기록: 상태(approved/unapproved/stopped/failed), 리뷰 라운드, 숨은 테스트 통과/전체, 소요 시간, 호출 수, CLI 별 입력·캐시·출력 토큰, Claude 비용(USD, 참고), 에이전트 자체 테스트 결과(마지막 duet 테스트).
- 승인 여부와 숨은 테스트 통과는 따로 본다: "승인했는데 숨은 테스트 실패" = 리뷰가 놓친 결함.

### 20.4 결과
- `<out>/<시각>/results.json`(실행별 행) + `summary.md`(워크플로별 집계: 실행 수, 승인률, 숨은 테스트 통과율 평균, 전부 통과한 비율, 승인했는데 실패한 수, 평균 라운드·시간·호출, 평균 토큰).
- `duet bench report <폴더>` 로 요약을 다시 출력, `duet bench list` 로 묶음·과제 목록.

### 20.5 어려운 과제 묶음 (`hard`)
`basic` 실측(2026-10-16): classic·lean 모두 5/5 승인, 숨은 테스트 100% — 과제가 쉬워 워크플로 차이를 가릴 수 없었다. `hard` 는 한 번에 맞히기 어려운 성질을 과제마다 하나 이상 넣는다. 인터페이스(이름·시그니처)는 채점을 위해 정확히 주되, 동작 명세에 함정을 둔다.

| 과제 | 종류 | 노리는 것 |
|---|---|---|
| `ledger` | 새 | 여러 모듈(파서·장부·보고서), 돈 계산(Decimal, 통화별 자릿수, 반올림 시점), 충돌하는 요구의 우선순위(합계 = 표시된 값의 합) |
| `csvq` | 새 | CSV 위 작은 질의 언어. 모호하기 쉬운 규칙을 명세로 고정: SQL 3값 논리(빈 값 = NULL, `!=`·`NOT` 도 거짓), NULL 은 정렬 방향과 상관없이 마지막, `007` 이 있으면 텍스트 열, 출력은 원문 그대로 |
| `ratelimit` | 새 | 동시성: 스레드 여러 개가 동시에 불러도 정확히 허용 수만큼만, 키별 리미터를 한 번만 생성, 시계가 거꾸로 가도 토큰 불변, 창 경계 |
| `ttlcache` | 새 | 성능: 모든 연산 상각 O(1)(10만 항목·30만 연산 시간 제한), 만료 경계, 가득 찼을 때 만료 항목부터 제거, `in` 은 사용으로 치지 않음, memoize 의 kwargs 순서 |
| `stock-reservations` | 기존 | 더 큰 기존 프로젝트(재고 관리, 모듈 5개·자체 테스트)에 예약 기능 추가: 출고가 예약을 존중, 조정은 막지 않음, 만료 경계, 저장 형식 v1 읽기·v2 쓰기·v3 거부, 목록 출력 열 추가 |

- 성능·동시성 테스트는 환경에 덜 민감하게: 시간 제한은 참조 구현의 5배 이상(실측 참조 0.1초대, 제한 6초), 경쟁 조건은 `sys.setswitchinterval` 을 줄이고 Barrier 로 동시에 출발시켜 드러낸다. 성능 테스트는 연산 도중에도 시간을 봐서 제한을 넘으면 바로 실패한다(느린 구현이 채점 시간 제한 300초를 다 써서 다른 테스트까지 0점이 되지 않게).
- 한계(실측): 일부러 틀린 구현으로 확인했을 때, 키별 리미터 중복 생성 경쟁은 매번 잡히지만, 버킷·창 하나 안의 경쟁(락 없이 확인 후 차감)은 CPython GIL 아래에서 바깥에서 거의 드러나지 않아 숨은 테스트로 확실히 잡지 못한다. 그 밖의 함정(반올림 방식, TOTAL 규칙, NULL 3값 논리·정렬, 만료 경계, 출고가 예약 무시, O(n) 만료 처리)은 모두 잡혔다.
- 참조 구현(`tests/bench_refs/`)으로 숨은 테스트를 검증하는 규칙은 `basic` 과 같다. 기존 프로젝트 과제는 시작 코드가 새 테스트만 실패하고 기존 테스트·자체 테스트는 통과하는지도 검증한다.

---

## 21. 리뷰 비용 줄이기

실측(hard 벤치마크): 두 워크플로 모두 비용의 큰 부분이 수정 라운드(구현자 + 리뷰어 재호출)다. 리뷰 한 번은 입력 12만~21만 토큰이었고 대부분 리뷰어가 도구 호출마다 다시 입력하는 문맥이다(17장). 그래서 (1) 리뷰어가 파일을 덜 열게, (2) 출력을 짧고 기계적으로, (3) 2라운드부터는 이미 읽은 것을 다시 읽지 않게 한다. 세 가지 모두 설정으로 끌 수 있어 벤치마크로 전후를 비교한다.

### 21.1 리뷰 패킷 (`review_packet = true`)
- 리뷰 프롬프트의 diff 를 **함수 단위 문맥**(`git diff --function-context`)으로 만든다. 크기 제한(`max_diff_chars`)을 넘으면 예전 diff 로 돌아간다.
- **바뀐 함수의 호출부**: diff 의 추가 줄과 hunk 머리에서 `def`/`class`/`function`/`fn`/`func` 로 정의된 이름을 모으고(최대 15개), `git grep -n -w` 로 작업 폴더에서 쓰이는 곳을 찾는다(정의 줄 제외, 이름당 5개, 전체 40줄). `[바뀐 함수가 쓰이는 곳]` 섹션.
- 안내 문구: "파일을 직접 열어봐도 된다" 대신 "패킷(diff·호출부·duet 테스트 결과)으로 먼저 판단하고, 패킷만으로 판단할 수 없을 때만 필요한 파일을 열어라. diff 에 이미 있는 내용은 다시 열지 마라".
- 템플릿 플레이스홀더 `{call_sites}`, `{read_instruction}`.

### 21.2 JSON 판정 (`review_json = true`)
- 리뷰 호출에 출력 스키마를 붙인다: Claude `--json-schema '<스키마>'`(결과 JSON 의 `structured_output`, 없으면 본문을 JSON 으로 읽음), Codex `--output-schema <파일>`(마지막 메시지를 JSON 으로 읽음).
- 스키마(엄격 모드 호환: 모든 필드 필수, 추가 필드 없음): `status`(APPROVED|CHANGES_REQUESTED), `summary`, `findings[]`(최대 12개: `severity` P1|P2|P3, `new`, `title`, `file`, `detail`, `evidence`), `repro[]`(최대 5개: `path`, `content`).
- duet 는 JSON 을 **기존 마크다운 리뷰 형식으로 바꿔** 기록한다(`## 반드시 고칠 것`/`## 고치면 좋은 것`, `<repro>` 블록, `<verdict>` 블록에 심각도별 개수). 그래서 판정 파싱·수정 프롬프트·재현 테스트·UI 는 그대로다. JSON 을 못 읽으면 본문을 예전 방식으로 읽는다(`parse_failed` 규칙 그대로).
- 템플릿의 출력 형식 안내는 `{output_instruction}` 으로 바뀐다(JSON 이면 스키마 안내, 아니면 예전 문구). 이 플레이스홀더가 없는 사용자 템플릿이면 그 호출은 JSON 을 쓰지 않는다.

### 21.3 리뷰어 세션 재사용 (`review_session = "reuse"`, `review_session_rounds = 3`)
- 2라운드부터 같은 역할의 리뷰어는 **자기** 직전 세션을 이어간다(구현자 세션은 절대 쓰지 않는다). 한 세션은 최대 `review_session_rounds` 라운드까지 쓰고 그다음엔 새 세션.
- Claude: 첫 리뷰 결과 JSON 의 `session_id` 를 저장하고 `claude -p --resume <id>`. Codex: 호출 직후 세션 기록에서 그 세션 id 를 찾아 저장하고 `codex exec resume <id>`. Codex 의 resume 에는 `--sandbox`·`-C` 가 없으므로 `-c sandbox_mode="read-only"` 로 읽기 전용을 유지한다.
- 이어간 리뷰의 프롬프트는 짧은 `rereview` 템플릿: 그 라운드의 diff(`review_diff` 설정을 따름, 기본은 지난 리뷰 이후만)·호출부·테스트 결과·자기 지난 '반드시 고칠 것' 목록과 "이전 지적이 해결됐는지 먼저 확인"만. 과제·설계·심각도 규칙은 세션에 이미 있다.
- 이어가기가 실패하면(한도·시간 초과가 아닌 비정상 종료) 어댑터가 같은 호출을 **새 세션 + 전체 프롬프트**로 한 번 다시 한다. 기록 메타에 `resumed`, `session_id`.
- 사용량: Codex 세션 기록의 토큰 수는 세션 누적값이라, 이어간 호출은 호출 시작 전 마지막 누적값과의 차이로 계산한다. Claude 의 `total_cost_usd` 는 이어간 세션에서 누적일 수 있다(참고값).
- `run.json` 의 `review_sessions`: 역할 → {id, rounds}.
