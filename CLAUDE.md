# CLAUDE.md

이 저장소는 `duet`을 만든다. 무엇을 만드는지는 **DESIGN.md가 기준**이다. 작업 시작 전에 DESIGN.md 전체를 읽어라.

## 작업 방식
- DESIGN.md 11장의 마일스톤(M0 → M6)을 **순서대로 하나씩** 진행한다.
- 각 마일스톤마다: 구현 → 테스트 작성 → `pytest` 통과 확인 → 완료 기준 점검 → 커밋(`M1: 실행부와 어댑터` 같은 메시지).
- 한 마일스톤을 끝내면 무엇을 했는지 3~5줄로 보고하고, 다음 마일스톤으로 넘어가기 전에 멈춘다. (사용자가 "계속"이라고 하면 진행)
- 설계에서 벗어나야 할 이유가 생기면 먼저 사용자에게 묻고, 합의되면 DESIGN.md도 함께 고친다. 몰래 바꾸지 않는다.

## 기술 규칙
- Python 3.11+, **런타임 의존성 없음**(표준 라이브러리만). 개발 의존성은 pytest만.
- `src/` 레이아웃, 타입 힌트 사용, dataclass 선호.
- 모든 subprocess 호출은 `duet.runner`를 통한다.
- 사용자에게 보이는 메시지(로그, 에러, README)는 한국어. 코드 식별자와 주석은 영어/한국어 자유.

## 절대 하지 말 것
- 테스트나 개발 중에 **실제 `claude -p`, `codex exec`로 프롬프트를 실행하지 않는다.** 사용자 구독 한도를 소모한다. `--help`, `--version` 확인만 허용(M1).
- Anthropic/OpenAI API SDK를 추가하지 않는다.
- `prototype/agent_team.py`를 수정하지 않는다. 참고만 한다.

## 명령어
- 설치: `pip install -e ".[dev]"`
- 테스트: `pytest -q`
- 수동 확인: `duet run "할일 CLI" --workdir /tmp/duet-try --mock`
- 관리자 UI: `duet ui` (느린 mock 으로 화면 확인: `DUET_MOCK_DELAY=1 duet ui`)
- UI 테스트는 `tests/test_ui.py`(HTTP 수준). 테스트는 `DUET_HOME` 을 임시 폴더로 바꿔 사용자의 `~/.duet` 을 건드리지 않는다.
