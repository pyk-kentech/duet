# duet

구독 중인 **Claude Code CLI**와 **Codex CLI**를 API 키 없이 헤드리스로 호출해, 두 모델이
**설계를 토론**하고 **서로의 코드를 교차 리뷰**하며 프로젝트를 완성하게 만드는 로컬 CLI 도구입니다.

- 설계 토론: 각자 설계안 → 상호 비판·개정(N라운드) → 결정권자가 `DESIGN.md` 종합
- 구현 + 교차 리뷰: 구현 담당이 코드 작성 → 리뷰 담당이 리뷰 → 승인될 때까지 수정 반복(최대 M회)
- 모든 발언·판정·커밋이 `<workdir>/.duet/runs/<run_id>/`에 남고, 중단해도 `duet resume`으로 이어갑니다.
- 실제 CLI 없이 `--mock`으로 전체 흐름을 확인할 수 있습니다.

설계 문서는 [DESIGN.md](DESIGN.md)를 보세요.

## 전제 조건

| 항목 | 요구 사항 |
|---|---|
| Python | 3.11 이상 (런타임 의존성 없음) |
| git | 작업 폴더를 git 저장소로 만들어 라운드마다 커밋합니다 |
| Claude Code | `claude` 명령이 PATH에 있고 **로그인된 상태** (`claude`를 한 번 대화형으로 실행해 로그인) |
| Codex CLI | `codex` 명령이 PATH에 있고 **로그인된 상태** (`codex login`) |

검증된 버전: Claude Code 2.1.300, codex-cli 0.162.1. 플래그가 달라지면 아래 설정으로 덮어쓸 수 있습니다.

## 설치

```bash
git clone <이 저장소> duet && cd duet
python3 -m venv .venv && . .venv/bin/activate      # 3.11+ 인터프리터로
pip install -e ".[dev]"
duet --help
pytest -q                                          # 실제 CLI를 호출하지 않는 테스트
```

venv를 활성화하지 않고도 어디서나 `duet`을 쓰려면 [uv](https://docs.astral.sh/uv/)로 설치합니다
(`~/.local/bin/duet`에 링크되며, `--editable`이라 저장소를 고치면 바로 반영됩니다):

```bash
uv tool install --python 3.12 --editable /path/to/duet
```

## 다른 머신에서 쓰기

duet는 실행하는 머신의 `claude`, `codex`를 부릅니다. 그래서 새 머신에도 두 CLI를 설치하고 각각 로그인해야 합니다.
같은 계정으로 로그인하면 구독 사용량 한도도 함께 씁니다.

| 머신에 필요한 것 | 확인 |
|---|---|
| Python 3.11+ 또는 [uv](https://docs.astral.sh/uv/) (uv가 Python을 받아 줌) | `python3 --version` / `uv --version` |
| git | `git --version` |
| Claude Code, 로그인 | `claude --version` 후 `claude` 한 번 실행 |
| Codex CLI, 로그인 | `codex --version`, `codex login` |

설치 방법은 셋 중 하나를 고르세요.

```bash
# A. css53 저장소에서 SSH로 바로 설치 (새 머신이 css53에 SSH 접속 가능할 때)
uv tool install --python 3.12 git+ssh://yonggamman@css53/home/yonggamman/duet

# B. 패키지 파일 복사 (css53에서 `uv build` 로 만든 dist/duet-0.1.0-py3-none-any.whl)
scp yonggamman@css53:duet/dist/duet-0.1.0-py3-none-any.whl .
uv tool install --python 3.12 ./duet-0.1.0-py3-none-any.whl
#   uv 가 없으면: python3.11 -m pip install --user ./duet-0.1.0-py3-none-any.whl

# C. GitHub 등 원격 저장소에 올린 뒤
uv tool install --python 3.12 git+https://github.com/<계정>/duet
```

- 최신으로 바꾸기: 같은 명령에 `--force`를 붙여 다시 설치합니다.
- 지원 OS: Linux, macOS. Windows는 WSL2 안에서 쓰세요(프로세스 그룹·시그널을 씁니다).
- 실행 기록은 각 머신의 작업 폴더(`.duet/`)에, 프로젝트 목록은 각 머신의 `~/.duet/`에 남습니다. 관리자 UI는 그 머신의 프로젝트만 보여줍니다.
- 다른 머신의 UI를 내 PC 브라우저로 보려면: `ssh -L 8787:127.0.0.1:8787 <그 머신>` 후 그 머신에서 `duet ui --no-browser`.

## 사용법

```bash
# 전체 실행 (설계 토론 → 구현 → 교차 리뷰)
duet run "마크다운 메모를 태그로 검색하는 CLI" --workdir ./memo-cli

# 긴 과제는 파일로
duet run @task.md --workdir ./memo-cli

# 설계 토론만 (처음 써볼 때 추천: 구독 사용량이 적음)
duet run "..." --workdir ./x --design-only

# 사람이 DESIGN.md를 손본 뒤 구현부터
duet run "..." --workdir ./x --skip-design

# 역할 바꾸기 / 라운드 조절
duet run "..." --workdir ./x --implementer codex --reviewer claude --debate-rounds 2 --max-review 5

# 중단된 실행 이어하기 (마지막 run 기준, --run <id> 로 특정 run)
duet resume --workdir ./x

# 리뷰 상한을 다 써서 미승인으로 끝났을 때: 상한을 늘려 마지막 리뷰 반영부터 이어가기
duet resume --workdir ./x --max-review 3

# 기록 보기
duet log --workdir ./x            # 최근 run 요약
duet log --workdir ./x --full     # 전체 발언을 순서대로 출력
duet log --workdir ./x --all      # 모든 run 한 줄씩

# CLI 없이 흐름 테스트
duet run "..." --workdir ./x --mock
```

실행 중 터미널에는 단계별 진행 상황이 한 줄씩 찍힙니다:

```
[17:41:38] 설계안 작성: claude
[17:41:38] claude ← propose 실행 중...
[17:42:19] claude ← propose 완료 (41초) → 01_propose_claude.md
...
[17:55:02] [1/3] 판정: CHANGES_REQUESTED (must_fix=2)
```

### 종료 코드

| 코드 | 의미 |
|---|---|
| 0 | 리뷰 승인으로 완료, 또는 `--design-only` 완료 |
| 1 | `max_review` 안에 승인되지 않음 (마지막 리뷰 파일 경로를 출력). `resume --max-review N`으로 이어갈 수 있음 |
| 2 | 사용 오류 (설정 값, 작업 폴더 가드, CLI 미설치 등) |
| 3 | 중단됨 (구독 한도 도달 또는 에이전트 반복 실패) → `duet resume` |
| 130 | 사용자가 멈춤 (Ctrl-C, 또는 관리자 UI의 중지) → `duet resume` |

## 환경 점검

```bash
duet doctor            # git, Claude Code·Codex CLI 설치·로그인 확인
```

빠진 것은 관리자 UI의 **환경·로그인** 화면에서 버튼으로 설치·로그인할 수 있습니다(공식 설치 스크립트만 실행).

## 모델 고르기

```bash
duet run "..." --workdir ./x --claude-model opus --claude-effort high --codex-model gpt-6.1-sol --codex-effort xhigh
```

비우면 각 CLI의 기본 모델을 씁니다. 매번 쓰기 번거로우면 UI의 **설정 > 기본 실행 설정**에 저장하세요(`~/.duet/settings.json`).
우선순위는 CLI 인자 > 작업 폴더의 `duet.toml` > 전역 설정 > 기본값입니다.

Codex 는 기본으로 단계마다 추론 강도를 다르게 씁니다(설계 종합·첫 리뷰 `high`, 나머지 `medium`). `--codex-effort xhigh` 처럼 하나만 주면 모든 단계에 그 값을 쓰고, 단계별로 바꾸려면 `--codex-step-effort review=xhigh,fix=low` 를 씁니다.

## 워크플로 템플릿

역할군과 단계 순서를 템플릿으로 골라 씁니다. 기본은 `classic`(지금까지의 Claude·Codex 토론 → 구현 → 교차 리뷰)입니다.

```bash
duet workflows                     # 쓸 수 있는 템플릿 목록
duet workflows show secure         # 역할·단계 자세히
duet run "..." --workdir ./x --workflow secure
```

| 내장 | 내용 |
|---|---|
| `secure` | classic + 보안 리뷰어(Codex, 보안 전용 프롬프트) + 승인 뒤 Claude 의 전체 감사 |
| `existing` | 기존 코드베이스용: Codex 가 먼저 코드를 조사하고 그 결과로 설계·구현 |
| `lean` | 가장 쌈: Claude 혼자 설계(토론 없음) → 구현 → Codex 리뷰 |

직접 만들려면 `<작업 폴더>/.duet/workflows/<이름>.toml` 또는 `~/.duet/workflows/<이름>.toml` 에 둡니다. 단계 종류는 `explore`(사전 조사), `debate`(설계), `build`(구현·리뷰, 리뷰어 최대 3명), `audit`(승인 뒤 감사, 참고용)입니다.

```toml
name = "my-team"
description = "Opus 설계자 + Sonnet 구현자 + Codex 두 명 리뷰"

[roles.architect]
agent = "claude"
model = "opus"
effort = "high"

[roles.coder]
agent = "claude"
model = "sonnet"

[roles.reviewer]
agent = "codex"

[roles.security]
agent = "codex"
templates = { review = "review_security" }   # 프롬프트 템플릿 교체
instructions = "인증·권한 코드를 특히 꼼꼼히 봐라."   # 이 역할의 프롬프트 끝에 붙는 지시

[[steps]]
kind = "debate"
proposers = ["architect", "reviewer"]
synth = "architect"

[[steps]]
kind = "build"
implementer = "coder"
reviewers = ["reviewer", "security"]   # 모두 승인해야 승인
max_review = 4
```

자세한 규칙은 DESIGN.md 19장에 있습니다.

## 리뷰 규칙과 테스트

- **duet가 직접 테스트**: 구현이 커밋되면 duet가 테스트를 돌리고 결과를 리뷰어와 구현자에게 보여줍니다. 명령은 `--test-command`, 구현자가 `duet.toml`에 적은 `test_command`, 자동 감지(pytest·npm·cargo·go·make) 순으로 정합니다. 테스트가 실패하면 리뷰어가 승인해도 승인하지 않습니다.
- **심각도 기준**: 리뷰어가 지적마다 P1(핵심 동작·보안)·P2(설계 위반·일반 입력 오류)·P3(드문 경계 사례)를 붙입니다. 기본은 P1·P2가 없으면 승인합니다(`--block-severity P3`면 P3까지 막음).
- **수렴 안 됨**: 막는 지적 수가 2라운드 연속 줄지 않으면 멈추고 사람에게 넘깁니다(`--stall-rounds`, 0이면 끔). `duet resume`으로 이어갈 수 있습니다.

- **재현 테스트**: 리뷰어가 지적을 실패하는 테스트로 내면 duet가 저장해 정말 실패하는지 돌려 보고, 구현자는 그 테스트를 통과시켜야 합니다.
- **리뷰 토큰 절약**: 2번째 리뷰부터는 지난 리뷰 이후 바뀐 부분만 보여주고, duet가 이미 돌린 테스트는 다시 돌리지 않게 합니다.

```bash
duet run "..." --workdir ./x --test-command "uv run pytest -q" --block-severity P2 --stall-rounds 2
```

관리자 UI에서 실행 중인 항목을 열면 AI가 지금 어떤 파일을 읽고 고치는지, 어떤 명령을 돌리는지 실시간으로 보입니다.

## 관리자 UI

```bash
duet ui                      # http://127.0.0.1:8787/?t=<토큰> 이 열립니다
duet ui --no-browser         # 주소만 출력
duet ui --workdir ~/proj     # 목록에 폴더 추가
```

- `duet run`으로 실행한 폴더는 자동으로 목록에 올라갑니다(`~/.duet/projects.json`).
- 실행 기록을 보고, 두 모델의 발언을 순서대로 읽고, 라운드별 diff와 진행 로그를 확인할 수 있습니다.
- 브라우저에서 새 실행, 이어하기(미승인이면 리뷰 상한 지정), 중지를 할 수 있습니다. UI를 꺼도 실행은 계속됩니다.
- 주소의 `?t=` 토큰이 있어야 열립니다. `duet ui`를 다시 시작하면 토큰이 바뀝니다.
- 원격 서버에서 쓸 때는 SSH 터널을 쓰세요: `ssh -L 8787:127.0.0.1:8787 <서버>` 후 로컬 브라우저에서 출력된 주소를 엽니다.

| 화면 | 할 수 있는 것 |
|---|---|
| 프로젝트 | 머신별 프로젝트·실행 기록, 발언 타임라인, diff, 진행 로그, 새 실행·이어하기·중지 |
| 환경·로그인 | 설치·로그인 상태 점검, 설치·로그인 버튼(터미널 창에서 코드·비밀번호 입력) |
| 사용량 | Codex 구독 한도(%)·초기화 시각, Claude Code 최근 5시간·7일 토큰, duet 실행별 토큰 |
| 설정 | 작업 폴더 위치, 기본 모델·추론 강도·역할, 원격 머신 |

### 원격 머신에서 돌리기

1. 이 머신에서 원격으로 비밀번호 없이 SSH 접속이 되게 합니다: `ssh-copy-id me@lab`
2. UI **설정 > 원격 머신**에 추가합니다(예: id `lab`, SSH `me@lab`, 작업 폴더 위치 `~/duet-projects`).
3. **환경·로그인 > lab**에서 '배포'를 누릅니다. 원격에 Python 3.11+만 있으면 되고, 없으면 같은 화면에서 uv → Python 3.12를 설치합니다.
4. 같은 화면에서 원격의 Claude Code·Codex를 설치·로그인합니다.
5. **새 실행**에서 머신을 `lab`으로 고르면 그 머신에서 돌고, 기록도 그 머신에 남습니다.

## 기록과 상태

```
<workdir>/.duet/runs/20261014-174138/
├── run.json                  # 상태 (resume 용)
├── 01_propose_claude.md
├── 02_propose_codex.md
├── 03_r1_critique_claude.md
├── 04_r1_critique_codex.md
├── 05_synthesize_codex.md    # → <workdir>/DESIGN.md 로 복사됨
├── 06_impl1_claude.md
├── 07_review1_codex.md
└── ...
```

- 각 기록 파일 상단에는 에이전트, 단계, 모드, 소요 시간, exit code가 HTML 주석으로 들어 있습니다.
- 호출이 실패하면 `..._failed.md` 로 stderr까지 남깁니다.
- `.duet/`는 자동으로 `.gitignore`에 추가됩니다.
- 진행 로그는 터미널과 함께 `console.log`에도 남습니다. 기존 `DESIGN.md`를 덮어쓸 때는 `DESIGN.prev.md`로 백업합니다.
- 같은 작업 폴더에서 duet를 동시에 두 개 돌릴 수 없습니다(`.duet/lock.json`).
- 커밋: `duet: design`(기준) → `duet: impl round 1` → `duet: impl round 2` → ...

## 설정 (`<workdir>/duet.toml`)

우선순위: CLI 인자 > `duet.toml` > 기본값. 아래는 기본값 전체입니다.

```toml
implementer = "claude"
reviewer = "codex"
synth = "codex"                  # 생략 시 reviewer
debate_rounds = 1                # 0~5
max_review = 3                   # 1~10
timeout_sec = 1200               # 호출 1회 제한
test_command = "auto"            # duet 가 돌릴 테스트 (auto: duet.toml → 자동 감지, none: 끔)
test_timeout_sec = 600
require_tests_pass = true        # 테스트 실패면 승인 안 함
block_severity = "P2"            # 이 심각도 이상 지적이 남으면 반려 (P1|P2|P3)
stall_rounds = 2                 # 막는 지적 수가 N 라운드 연속 안 줄면 멈춤 (0=끔)
review_diff = "incremental"      # 2번째 리뷰부터 바뀐 부분만 (full: 매번 전체)
repro_tests = true               # 리뷰어의 재현 테스트를 저장·실행
max_diff_chars = 60000           # 리뷰 프롬프트에 넣을 diff 최대 길이
prompt_arg_max_bytes = 100000    # UTF-8 바이트. 넘으면 프롬프트를 stdin으로 전달
diff_excludes = ["package-lock.json", "yarn.lock", "uv.lock", "poetry.lock", "Cargo.lock", "go.sum", "..."]  # 리뷰 diff 에서 뺄 잠금 파일 (기본값 일부)

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

CLI 버전이 바뀌어 플래그가 달라지면 `claude --help`, `codex exec --help`로 확인해 여기서 고치면 됩니다.

## 프롬프트 커스터마이즈

기본 템플릿은 `src/duet/templates/*.md`에 있습니다. `<workdir>/.duet/templates/`에 같은 이름의 파일을
두면 그것을 우선 사용합니다.

| 파일 | 쓰는 곳 | 플레이스홀더 |
|---|---|---|
| `propose.md` | 설계안 작성 | `{task}` |
| `critique.md` | 상대 안 비판 + 개정안 | `{task}`, `{own}`, `{other}`, `{other_name}` |
| `synthesize.md` | 최종 설계 종합 | `{task}`, `{a}`, `{b}`, `{a_name}`, `{b_name}`, `{critiques}` |
| `implement.md` | 첫 구현 | `{task}` |
| `fix.md` | 리뷰 반영 | `{task}`, `{review}`, `{reviewer_name}` |
| `review.md` | 코드 리뷰 | `{task}`, `{diff}`, `{implementer_name}` |

- 중괄호를 문자 그대로 쓰려면 `{{`, `}}`.
- `critique.md`는 응답에 `## 개정안` 헤더를 요구합니다. 그 뒤가 다음 라운드의 설계안이 됩니다(없으면 응답 전체).
- `review.md`는 응답 마지막에 판정 블록을 요구합니다. 레거시 `VERDICT: APPROVED` 한 줄도 인식합니다.

```
<verdict>
status: APPROVED | CHANGES_REQUESTED
must_fix: 0
</verdict>
```

둘 다 없으면 반려로 간주하고, `APPROVED`인데 `must_fix > 0`이면 모순으로 보아 반려 처리합니다.

## 주의사항

- **구독 사용량**: 한 번의 `run`은 `2 + 2×debate_rounds + 1 + 2×(리뷰 반복 수)` 회의 CLI 호출을 합니다.
  처음에는 `--design-only`로 가볍게 시작하세요. 한도에 걸리면 상태를 저장하고 종료하므로 나중에 `duet resume` 하면 됩니다.
- **작업 폴더 가드**: 홈 디렉터리나 `/`는 거부합니다. 기존 git 저장소에 커밋 안 된 변경이 있으면 거부합니다(`--force`로 무시).
- **리뷰어 쓰기 차단**: 리뷰는 읽기 전용 모드로 호출하고, 리뷰 후 작업 트리에 변경이 있으면 경고 후 되돌립니다(`.duet/` 제외).
- **구현자는 셸을 실행합니다**: Claude는 `Bash`, Codex는 `workspace-write` 샌드박스로 테스트 등을 실행합니다. 믿을 수 있는 폴더에서만 쓰세요.
- **약관**: 공식 CLI를 본인 PC에서 개인 용도로만 사용합니다. 웹 화면 자동화나 비공식 API 호출은 하지 않습니다.
- 테스트(`pytest`)는 실제 `claude`/`codex`를 호출하지 않습니다(`tests/fake_bin`의 가짜 실행 파일 사용).

## 개발

```bash
pytest -q                                              # 전체 테스트
duet run "할일 CLI" --workdir /tmp/duet-try --mock      # 수동 흐름 확인
```

구조와 마일스톤은 [DESIGN.md](DESIGN.md), 작업 규칙은 [CLAUDE.md](CLAUDE.md)에 있습니다.
