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
max_diff_chars = 60000           # 리뷰 프롬프트에 넣을 diff 최대 길이
prompt_arg_max_chars = 100000    # 넘으면 프롬프트를 stdin으로 전달

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
