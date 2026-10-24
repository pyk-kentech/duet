# findex 설계

## 모듈

| 모듈 | 역할 |
|---|---|
| `findex/errors.py` | 오류 계층 (`FindexError` 아래 `DocumentNotFound`, `QuerySyntaxError`, `StorageError`) |
| `findex/textutil.py` | 문자열 도우미: 문자 비교 정규형 `normalize`(NFKD → Mn 제거 → casefold → NFC)와 태그 키 `tag_key`, 단어 글자 판정, 스니펫 자르기 |
| `findex/tokenizer.py` | 원문 → `Token(text, start, end)` (아포스트로피·소수점·결합 표시 규칙), 하이픈 단어 묶기 `iter_words` |
| `findex/stemmer.py` | 단순 접미사 어간 추출 |
| `findex/analyzer.py` | `Analyzer`: 토큰 → 정규화 → 불용어 → 어간, 위치 붙이기. 설정(불용어·어간) 보관 |
| `findex/document.py` | `Document` 와 입력 검증(제목·태그·날짜), 여러 문서 검증(전부 아니면 전무), JSON Lines 읽기·쓰기 |
| `findex/index.py` | `InvertedIndex`: 필드별 `색인어 → {문서 id: [위치]}`, 텍스트 필드 길이, 문서별 색인어(정방향, 지우기용), 정렬된 색인어(접두어용) |
| `findex/scoring.py` | BM25, 필드 가중치, `CorpusStats`(문서 수·필드 길이 합, 넣고 뺄 때 바로 고침) |
| `findex/synonyms.py` | 동의어 묶음(등록·합치기·검색 때 확장) |
| `findex/query.py` | 검색어 렉서·파서 → AST (`TermQ`, `PhraseQ`, `PrefixQ`, `TagQ`, `DateQ`, `AndQ`, `OrQ`, `NotQ`) |
| `findex/search.py` | `Searcher`: AST 평가 → `{문서 id: 점수}`, 정렬·페이지, explain/similar 도우미 |
| `findex/highlight.py` | 강조할 단어 찾기, 표시 넣기, 스니펫 |
| `findex/facets.py` | 태그별 문서 수 |
| `findex/suggest.py` | 자동 완성, 철자 교정(편집 거리) |
| `findex/engine.py` | `Index`: 공개 API. 문서 저장소 + 역색인 + 통계를 묶는다 |
| `findex/storage.py` | JSON 저장(형식 버전 3)·읽기(버전 1, 2, 3, 언제나 다시 색인) |
| `findex/cli.py` | argparse 하위 명령 |

## 데이터 흐름

- **넣기**: `Index.add` → `document.make_document`(검증) → 텍스트 필드마다 `Analyzer.analyze` →
  `InvertedIndex.add_field`, 태그는 태그 키로 `add_tags` → `CorpusStats` 갱신.
- **검색**: `query.parse` → AST → `Searcher.evaluate`(단어는 `Analyzer.query_terms`, 구절은
  `Analyzer.phrase_terms` 로 분석하고 `SynonymTable.expand` 로 넓힌 뒤 `InvertedIndex` 의 postings 로 BM25)
  → `search.order` → `search.paginate`.
- **강조**: AST 의 긍정 조각들(동의어까지)로 `highlight.Matcher` 를 만들고, 원문을 색인과 같은 토크나이저
  (`iter_words`)로 다시 훑어 원문 위치를 찾는다.
- **저장**: `storage.dump` 가 문서·설정(동의어 포함)·`next_id` 를 JSON 으로(역색인은 저장하지 않음). 읽을 때는
  버전과 상관없이 문서로부터 다시 색인한다.
- **성능**: 넣기·지우기·고치기는 그 문서의 색인어만 건드리고 통계는 바로 고친다. 접두어 검색·자동 완성은
  정렬된 색인어 목록에서 이분 탐색한다.

## 규칙

- 지운 문서는 저장소에 `None` 으로 남겨 id 를 예약한다. 다음 id 는 `_next_id` 카운터(저장 파일의 `next_id`).
- 문자 비교는 `textutil.normalize` 하나만 쓴다(정규화 코드를 여러 곳에 두지 않는다).
- 공개 API 는 `findex/__init__.py` 에서 내보내는 이름과 `Index` 의 메서드다. CLI 출력 형식은 스크립트가 읽으므로 바꾸지 않는다.
- 저장 형식이 바뀌면 `version` 을 올리고 이전 버전 파일도 읽을 수 있게 한다.
- 시간·난수에 기대지 않는다(결과가 늘 같아야 한다).
- 테스트: `tests/` (pytest).
