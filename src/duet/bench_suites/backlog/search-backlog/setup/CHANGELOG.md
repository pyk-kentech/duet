# 변경 기록

## 0.4.2
- `Index.check()`, CLI `check`: 색인이 문서와 맞는지 검사.
- CLI `parse`, `--version`.

## 0.4.1
- 철자 교정 `Index.correct()`, CLI `correct`.
- `Index.vocabulary()`, CLI `terms`. `get --highlight`.
- `Index.merge()`, CLI `merge`.

## 0.4.0
- 저장 형식 **버전 2**: 역색인을 함께 저장해 읽을 때 다시 분석하지 않는다(큰 색인을 여는 시간이 줄었다).
  버전 1 파일은 계속 읽는다. 분석 규칙을 바꾼 뒤에는 `reindex` 로 다시 만든다.
- 설정(불용어·어간·가중치)을 파일에 저장한다.
- 자동 완성 `Index.suggest()`, CLI `suggest`.

## 0.3.0
- `similar`, `explain`.
- `search --json` (점수 반올림 없음). 표 출력은 계속 소수 넷째 자리.
- `import` 는 전부 아니면 전무.

## 0.2.0
- 날짜 필터 `date:` (부분 날짜, 열린 범위).
- facets 이름은 그 태그를 가진 문서 중 id 가 가장 작은 문서의 철자.
- 지운 문서의 id 를 다시 쓰지 않는다(저장했다가 읽어도).

## 0.1.0
- 처음 공개: 색인·BM25 검색·구절·접두어·태그 필터·스니펫·JSON 저장(버전 1)·CLI.
