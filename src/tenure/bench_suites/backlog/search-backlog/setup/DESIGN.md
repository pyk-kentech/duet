# findex 설계

## 모듈

| 모듈 | 역할 |
|---|---|
| `findex/errors.py` | 오류 계층 (`FindexError` 아래 `DocumentNotFound`, `QuerySyntaxError`, `StorageError`) |
| `findex/textutil.py` | 문자열 도우미: 색인어 표준형 `normalize`, 단어 글자 판정, 스니펫 자르기 |
| `findex/tokenizer.py` | 원문 → `Token(text, start, end)` (아포스트로피·소수점 규칙) |
| `findex/stemmer.py` | 단순 접미사 어간 추출 |
| `findex/analyzer.py` | `Analyzer`: 토큰 → 정규화 → 불용어 → 어간, 위치 붙이기. 설정(불용어·어간) 보관 |
| `findex/document.py` | `Document` 와 입력 검증(제목·태그·날짜), 여러 문서 검증(전부 아니면 전무), JSON Lines 읽기·쓰기 |
| `findex/index.py` | `InvertedIndex`: 필드별 `색인어 → {문서 id: [위치]}`, 텍스트 필드 길이 |
| `findex/scoring.py` | BM25, 필드 가중치, `CorpusStats`(문서 수·필드 길이 합) |
| `findex/query.py` | 검색어 렉서·파서 → AST (`TermQ`, `PhraseQ`, `PrefixQ`, `TagQ`, `DateQ`, `AndQ`, `OrQ`, `NotQ`) |
| `findex/search.py` | `Searcher`: AST 평가 → `{문서 id: 점수}`, 정렬·페이지, explain/similar 도우미 |
| `findex/highlight.py` | 강조할 단어 찾기, 표시 넣기, 스니펫 |
| `findex/facets.py` | 태그별 문서 수 |
| `findex/suggest.py` | 자동 완성, 철자 교정(편집 거리) |
| `findex/engine.py` | `Index`: 공개 API. 문서 저장소 + 역색인 + 통계를 묶는다 |
| `findex/storage.py` | JSON 저장(형식 버전 2)·읽기(버전 1, 2) |
| `findex/cli.py` | argparse 하위 명령 |

## 데이터 흐름

- **넣기**: `Index.add` → `document.make_document`(검증) → 텍스트 필드마다 `Analyzer.analyze` →
  `InvertedIndex.add_field`, 태그는 태그 키로 `add_tags` → `CorpusStats` 갱신.
- **검색**: `query.parse` → AST → `Searcher.evaluate`(필요할 때 `Analyzer.query_terms` 로 단어 분석,
  `InvertedIndex` 에서 postings 를 읽어 BM25) → `search.order` → `search.paginate`.
- **강조**: AST 의 긍정 조각들로 `highlight.Matcher` 를 만들고 원문을 다시 훑어 위치를 찾는다
  (원문 위치가 필요해서 토크나이저 결과 대신 정규식으로 다시 훑는다).
- **저장**: `storage.dump` 가 문서·설정·역색인을 그대로 JSON 으로. 읽을 때 버전 2 는 역색인을 그대로
  쓰고(빠르다), 버전 1 은 문서로 다시 만든다. 분석 규칙을 바꾸면 `Index.reindex` 로 다시 만든다.

## 규칙

- 지운 문서는 저장소에 `None` 으로 남겨 id 를 예약한다. 다음 id 는 `_next_id` 카운터.
- 공개 API 는 `findex/__init__.py` 에서 내보내는 이름과 `Index` 의 메서드다. CLI 출력 형식은 스크립트가 읽으므로 바꾸지 않는다.
- 저장 형식이 바뀌면 `version` 을 올리고 이전 버전 파일도 읽을 수 있게 한다.
- 시간·난수에 기대지 않는다(결과가 늘 같아야 한다).
- 테스트: `tests/` (pytest).
