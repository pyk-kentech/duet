설정 값을 겹쳐 쓰는 Python 패키지 `deepmerge` 를 만든다.

- 패키지는 작업 폴더 최상위의 `deepmerge/` 에 둔다 (src 레이아웃을 쓰지 말 것). 표준 라이브러리만 쓴다.
- 입력은 JSON 이나 TOML 에서 읽은 설정이다. 값은 `dict`(키는 `str`), `list`, `str`, `int`, `float`, `bool`, `None` 뿐이다.
- 아래 이름과 동작을 정확히 지킨다. 다른 사람이 이 인터페이스로 테스트한다.

## `deepmerge.merge(base, override) -> dict`

- `base`·`override` 는 `dict`. 아니면 `TypeError`.
- 둘 다 가진 키의 값이 둘 다 `dict` 면 재귀로 병합한다. 그 밖에는 `override` 의 값이 이긴다.
- 리스트는 이어 붙이지 않고 `override` 의 리스트로 통째로 바꾼다.
- `override` 의 값이 `None` 이면 그 키를 결과에서 지운다(`base` 에 없으면 무시). 중첩된 곳에서도 같다.
- 키 순서: `base` 의 키 순서를 유지하고, 새 키는 `override` 의 순서대로 뒤에 붙인다.
- 입력을 바꾸지 않는다. 결과는 입력과 객체를 공유하지 않는다(결과의 중첩 dict·list 를 고쳐도 입력은 그대로).

## `deepmerge.merge_all(*configs) -> dict`

- 왼쪽부터 차례로 `merge` 한 결과. 인자가 없으면 `{}`. 하나면 그 복사본.

## `deepmerge.parse_overrides(items) -> dict`

- `["server.port=8080", "debug=true", "name=api"]` → `{"server": {"port": 8080}, "debug": True, "name": "api"}`.
- 각 항목은 `키경로=값`. 첫 `=` 에서 나눈다. 키경로는 `.` 으로 나눈 이름들이고, 빈 이름이 있으면(예: `a..b`, `=1`) `ValueError`. `=` 가 없어도 `ValueError`.
- 값은 JSON 으로 읽어 보고(`8080`, `true`, `null`, `[1,2]`, `"x"`), JSON 이 아니면 그대로 문자열.
- 같은 경로가 여러 번 나오면 뒤의 것이 이긴다. 결과는 `merge` 에 그대로 넘길 수 있다(`null` 은 지우기).
