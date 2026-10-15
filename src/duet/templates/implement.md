현재 디렉터리의 DESIGN.md를 읽고 그 설계대로 프로젝트를 구현해라.
과제: {task}

- 설계에서 벗어나야 하면 이유를 IMPLEMENTATION_NOTES.md에 적어라.
- 테스트를 작성하고 직접 실행해 통과하는지 확인해라.
- 구현이 끝나면 duet 가 테스트를 직접 실행한다. 테스트를 돌리는 한 줄 명령을 작업 폴더의 duet.toml 에
  `test_command = "..."` 로 적어라 (예: `python3 -m pytest -q`, `uv run pytest -q`, `npm test --silent`).
  duet.toml 이 이미 있으면 그 줄만 추가하거나 고치고 다른 설정은 건드리지 마라.
  {test_hint}
- DESIGN.md는 수정하지 마라.
- .duet/ 디렉터리는 건드리지 마라.

작업이 끝나면 무엇을 만들었는지 짧게 요약해라.
