현재 디렉터리의 {design_doc}를 읽고 그 설계대로 프로젝트를 구현해라.
과제: {task}
{design_note}

- 과제 원문이 가장 우선이다. {design_doc}가 과제 원문과 다르거나 과제의 요구·인터페이스·예시를 빠뜨렸으면 과제 원문을 따르고, 그 점을 IMPLEMENTATION_NOTES.md 에 적어라.
- 설계에서 벗어나야 하면 이유를 IMPLEMENTATION_NOTES.md에 적어라.
- 테스트를 작성하고 직접 실행해 통과하는지 확인해라.
- 구현이 끝나면 tenure 가 테스트를 직접 실행한다. 테스트를 돌리는 한 줄 명령을 작업 폴더의 tenure.toml 에
  `test_command = "..."` 로 적어라 (예: `python3 -m pytest -q`, `uv run pytest -q`, `npm test --silent`).
  tenure.toml 이 이미 있으면 그 줄만 추가하거나 고치고 다른 설정은 건드리지 마라.
  {test_hint}
- {design_doc}는 수정하지 마라.
- .tenure/ 디렉터리는 건드리지 마라.

작업이 끝나면 무엇을 만들었는지 짧게 요약해라.
