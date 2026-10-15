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

- `.duet/`는 자동으로 `.gitignore`에 추가.
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

