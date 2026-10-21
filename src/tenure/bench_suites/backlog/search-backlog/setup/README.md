# findex

표준 라이브러리만 쓰는 작은 전문(full-text) 검색 라이브러리와 CLI. Python 3.11 이상.

```python
from findex import Index

idx = Index()
a = idx.add("Lord of the Rings", body="A long journey with the ring.", tags=["Fantasy", "books"], date="2001-12-19")
b = idx.add("Ring theory", body="Groups, rings and fields.", tags=["math"])

res = idx.search("ring")
res.total            # 2
res.hits[0].doc_id   # 1  (제목에 맞은 문서가 위)
idx.snippet(b, "ring")      # 'Groups, [rings] and fields.'
idx.facets()                # [('books', 1), ('Fantasy', 1), ('math', 1)]
idx.save("books.json")
idx2 = Index.load("books.json")
```

테스트: `python -m pytest -q`

---

## 문서

문서는 `id`, `title`, `body`, `tags`, `date` 를 가진다 (`findex.Document`, 바꿀 수 없는 값).

- `title`: 앞뒤 공백을 뗀 뒤 비어 있으면 `ValueError`. 저장은 넣은 문자열 **그대로**.
- `body`: 문자열, 그대로 저장.
- `tags`: 문자열 목록. 각 태그의 앞뒤 공백을 떼고, 빈 태그는 버리고, 대소문자만 다른 같은 태그가
  여러 번 있으면 처음 것만 남긴다. 남은 태그는 쓴 철자 그대로다.
- `date`: `YYYY-MM-DD` 또는 `None`. 문서 날짜는 **완전한 날짜만** 받는다(`2024-03` 은 `ValueError`).
  부분 날짜는 검색어의 날짜 범위에서만 쓴다.

### id

- id 는 1 부터 차례로 붙는 정수다.
- **지운 문서의 id 는 다시 쓰지 않는다.** 다음 id 는 지금까지 붙인 가장 큰 id + 1 이다. 가장
  마지막 문서를 지운 뒤에도, 저장했다가 다시 읽은 뒤에도 그렇다.
- `update` 는 id 를 바꾸지 않는다.
- 없는 id 나 지운 id 로 `get`/`update`/`delete` 를 하면 `DocumentNotFound`.

## API (`findex.Index`)

| 메서드 | 설명 |
|---|---|
| `Index(*, stopwords=None, stem=True, boosts=None)` | `stopwords` 가 `None` 이면 기본 영어 불용어, 목록을 주면 그것으로 **바꾼다**(빈 목록 = 불용어 없음). `boosts` 는 필드 가중치(기본 `{"title": 2.0, "body": 1.0}`, 양수만) |
| `add(title, body="", tags=(), date=None) -> int` | 새 id |
| `add_many(items) -> list[int]` | dict 목록. **전부 아니면 전무**: 하나라도 틀리면 `ValueError`(몇 번째 항목인지 적힘), 아무것도 넣지 않음 |
| `merge(other) -> list[int]` | 다른 색인의 문서를 모두 새 id 로 넣는다(설정은 이 색인 것) |
| `update(doc_id, *, title=None, body=None, tags=None, date=None) -> Document` | 준 필드만 바꾼다. `None` 은 그대로 둔다 |
| `delete(doc_id)` | 지운다 |
| `get(doc_id) -> Document`, `documents()`, `ids()`, `len(idx)`, `doc_id in idx`, `idx.next_id` | 조회 (지운 문서는 빠진다) |
| `search(query, *, page=1, per_page=10, sort="score") -> SearchResults` | `.total`(전체 맞은 수), `.hits`(이 페이지의 `Hit(doc_id, score, title)`), `.page`, `.per_page`, `.pages`, `.ids()` |
| `count(query) -> int` | 맞은 문서 수 |
| `facets(query=None, *, limit=None)` | `[(태그 이름, 문서 수)]` |
| `highlight(doc_id, query, *, field="title", markers=("[", "]")) -> str` | 필드 전체에 강조 표시 |
| `snippet(doc_id, query, *, length=120, markers=("[", "]")) -> str` | 본문 스니펫 |
| `suggest(prefix, *, limit=10)` | 자동 완성 `[(색인어, 문서 수)]` |
| `correct(query) -> str \| None` | 철자를 고친 검색어 (고칠 것이 없으면 `None`) |
| `similar(doc_id, *, limit=5) -> list[Hit]` | 비슷한 문서 |
| `explain(doc_id, query)` | 점수 풀이 (디버깅용, 형식이 바뀔 수 있음) |
| `vocabulary(*, field=None, limit=20)` | 많은 문서에 나온 색인어 `[(색인어, 문서 수)]` (문서 수 내림차순, 같으면 색인어 순) |
| `stats()` | `{"documents", "terms", "next_id"}` |
| `reindex() -> int` | 문서로부터 역색인·통계를 다시 만든다(다시 색인한 문서 수) |
| `check() -> list[str]` | 색인이 문서와 맞는지 검사(고장 진단용). 문제 목록(없으면 빈 목록) |
| `save(path)`, `Index.load(path)` | 저장·읽기 |
| `import_jsonl(path) -> list[int]`, `export_jsonl(path) -> int` | JSON Lines 넣기(전부 아니면 전무)·내보내기 |

오류: `FindexError` 아래 `DocumentNotFound`, `QuerySyntaxError`, `StorageError`. 입력값 검증은 `ValueError`.

## 토큰과 분석

색인과 검색어는 같은 분석을 거친다: 토큰 자르기 → 정규화 → 불용어 빼기 → 어간 추출.

- **토큰**: 단어 글자(유니코드 글자·숫자·밑줄)가 이어진 것. 한글도 공백이나 문장부호가 나올 때까지
  한 토큰이다. 밑줄은 단어 글자다(`snake_case` 는 한 토큰).
  - 두 글자 사이의 아포스트로피(`'`, `’`)는 지우고 잇는다: `don't` → `dont`, `O’Brien` → `obrien`.
  - 두 숫자 사이의 마침표는 남긴다: `3.14` 는 한 토큰(그래서 `14` 로는 찾을 수 없다).
  - 그 밖의 문자(공백, 문장부호, 하이픈, 기호)는 토큰을 가른다: `e-mail` → `e`, `mail`.
- **정규화**: NFC 로 합친 뒤 casefold (`Straße` → `strasse`). 대소문자는 구분하지 않는다.
- **불용어**: 기본 영어 불용어(`findex.DEFAULT_STOPWORDS`: a, an, and, the, of, or, not, ...).
  불용어도 정규화해서 비교한다.
- **위치**: 불용어는 위치를 차지하지 않는다. 남은 단어에 0, 1, 2... 를 붙인다.
  그래서 **구절 검색은 불용어 자리를 무시한다**: `"lord of the rings"` 는 `Lord of the Rings`,
  `lord rings`, `Lord of Rings` 모두에 맞는다.
- **어간**: 단순한 접미사 규칙(`findex/stemmer.py` 의 표). 3글자 이하, 숫자가 섞인 단어는 그대로.
  예: `cats` → `cat`, `running` → `run`, `studies` → `study`, `classes` → `class`, `news` → `news`.
  `Index(stem=False)` 면 끈다.

## 검색어

| 쓰는 법 | 뜻 |
|---|---|
| `apple pie` | 둘 다 있는 문서 (나란히 쓰면 AND) |
| `apple AND pie`, `apple OR pie`, `NOT pie` | 연산자는 **대문자일 때만**. 소문자 `and`/`or`/`not` 은 보통 단어(기본 설정에서는 불용어라 무시) |
| `-pie` | `NOT pie` 의 줄임. 토큰 맨 앞의 `-` 만 그렇다. `-"구절"`, `-(a b)`, `-tag:x` 도 된다. 홀로 선 `-` 는 무시 |
| `( ... )` | 묶음. 우선순위는 NOT > AND > OR |
| `"apple pie"` | 구절 (큰따옴표만). 단어들이 이 순서로 붙어 있어야 한다(불용어 자리는 무시) |
| `title:apple`, `body:apple`, `title:"apple pie"` | 그 필드만 |
| `appl*` | 접두어: 색인어(어간 형태) 중 이 글자로 시작하는 것. `*` 앞은 2글자 이상(아니면 `QuerySyntaxError`), 대소문자 무시, 어간 추출 안 함. `title:appl*` 도 된다 |
| `tag:python`, `tag:"machine learning"` | 태그 필터: 태그 **전체**가 같아야 한다(대소문자 무시). 점수 없음 |
| `date:2024-01-01..2024-03-31` | 날짜 필터(양 끝 포함). `2024..`, `..2024-06`, `2024-02`(그 달 전체), `2024`(그 해 전체)처럼 부분 날짜와 열린 범위를 쓸 수 있다. 날짜 없는 문서는 맞지 않는다. 점수 없음 |

- 필드 이름은 소문자로 쓴다. 모르는 이름이 붙은 단어(`foo:bar`)는 보통 단어로 본다.
- 한 단어가 분석 후 여러 색인어가 되면(`foo.bar`, `x/y`, `e-mail` 처럼 문장부호가 낀 경우) 그
  색인어들의 **구절**로 찾는다: `foo.bar` 는 `"foo bar"` 와 같다.
- 불용어뿐인 조각은 무시한다(`the cat` = `cat`). 검색어 전체가 불용어뿐이거나 비어 있으면 결과 0건(오류 아님).
- NOT 만 있는 검색어(`-draft`)는 그것에 맞지 않는 모든 문서를 돌려준다(점수 0).
- 문법 오류(닫히지 않은 따옴표·괄호, 빈 괄호, 연산자 뒤에 검색어 없음, 잘못된 날짜)는 `QuerySyntaxError`.

## 점수

필드마다 BM25 를 구해 필드 가중치를 곱해 더한다.

- `idf = ln(1 + (N - df + 0.5) / (df + 0.5))` — `N` 은 (지우지 않은) 문서 수, `df` 는 그 필드에 그 색인어가 있는 문서 수.
- `bm25 = idf × tf × (k1 + 1) / (tf + k1 × (1 - b + b × len / avglen))`, `k1 = 1.2`, `b = 0.75`.
  `len` 은 문서의 필드 길이(분석 후 색인어 수), `avglen` 은 지우지 않은 문서들의 평균 필드 길이(0 이면 1).
- 구절: `tf` = 구절이 나온 횟수, `df` = 구절이 있는 문서 수.
- 접두어: 펼친 색인어들을 **한 단어처럼**: `tf` = 그 색인어들의 tf 합, `df` = 하나라도 가진 문서 수.
- AND·OR 는 맞은 조각들의 점수를 더한다. NOT·`tag:`·`date:` 는 점수에 더하지 않는다.
- 정렬(`sort="score"`): 점수 내림차순, 같으면 id 오름차순. `sort="date"`: 날짜 최신순, 날짜 없는 문서는 맨 뒤, 같으면 id 순.
- **API 의 점수는 반올림하지 않는다. CLI 의 표 출력만 소수 넷째 자리로 반올림한다**(`search --json` 은 반올림하지 않는다).

## 페이지

`page` 는 1 이상, `per_page` 는 1~100 (아니면 `ValueError`). 범위를 넘은 페이지는 `hits` 가 비어 있고 `total` 은 그대로다.

## facets

- 대소문자만 다른 태그는 같은 태그로 센다. 한 문서는 같은 태그를 한 번만 센다.
- **이름은 그 태그를 가진 문서 중 id 가 가장 작은 문서의 철자**다(그 문서를 지우면 다음 문서의 철자).
- 정렬: 개수 내림차순, 같으면 이름을 casefold 한 사전순. `limit` 을 주면 앞에서 그만큼.
- `facets(query)` 는 그 검색에 맞은 문서(페이지와 상관없이 전부)만 센다.

## 강조와 스니펫

- 원문은 바꾸지 않고 맞은 단어 앞뒤에 표시(기본 `[`, `]`)만 넣는다. 대소문자·철자는 원문 그대로.
- 강조 대상: NOT 아래가 아닌 단어·구절·접두어. `tag:`·`date:` 는 강조하지 않는다. 필드를 정한 조각(`title:x`)은 그 필드에서만.
- **구절의 단어는 구절로 붙어 있지 않아도 각각 강조한다.**
- 비교는 색인과 같은 규칙(대소문자 무시, 어간)으로 한다. 불용어는 강조하지 않는다. 접두어는 그 접두어로 시작하는 단어를 강조한다.
- 스니펫(본문):
  - 본문이 `length`(기본 120) 글자 이하이면 본문 전체.
  - 맞은 단어가 없으면 앞에서 `length` 글자 안의 마지막 공백까지.
  - 있으면 첫 번째 맞은 단어의 30글자 앞(그 사이 첫 공백 다음)에서 시작해 `length` 글자 안의 마지막 공백까지.
  - 앞이 잘렸으면 맨 앞에, 뒤가 잘렸으면 맨 뒤에 `…`. 줄바꿈·연속 공백은 공백 하나로.

## 자동 완성 (`suggest`)

`title`·`body` 의 색인어(정규화·어간 형태) 중 `prefix` 로 시작하는 것과 그 색인어가 있는 문서 수.
문서 수 내림차순, 같으면 색인어 순. `prefix` 는 대소문자 무시, 비어 있으면 빈 목록.

## 철자 교정 (`correct`)

검색어의 단어 중 색인에 없는 것을 편집 거리(글자 넣기·빼기·바꾸기, 이웃한 두 글자 맞바꾸기) 2 이하인
색인어 중 가장 가까운 것(거리 → 문서 수 많은 것 → 색인어 순)으로 바꾼 검색어를 돌려준다. 연산자, 필드가
붙은 단어, 접두어, 구절, 괄호가 붙은 단어, `-` 로 시작하는 단어는 건드리지 않는다. 글자로만 된 4글자
이상 단어만 고치고, 고친 단어는 색인어(어간 형태)로 바뀐다: `pyhton tipz` → `python tip`.

## 저장 형식 (JSON)

지금 형식은 **버전 2**:

```json
{
  "format": "findex",
  "version": 2,
  "settings": {"stopwords": null, "stem": true, "boosts": {"title": 2.0, "body": 1.0}},
  "documents": [{"id": 1, "title": "...", "body": "...", "tags": ["..."], "date": "2024-01-31"}],
  "index": {
    "next_id": 4,
    "fields": {"title": {"색인어": {"1": [0]}}, "body": {}, "tags": {"태그 키": {"1": [0]}}},
    "lengths": {"title": {"1": 3}, "body": {"1": 0}}
  }
}
```

- `settings.stopwords` 는 `null`(기본 불용어) 또는 단어 목록. `documents` 에는 지우지 않은 문서만 id 순으로.
- `index.next_id` 는 다음 id(지운 id 를 다시 쓰지 않으려고 저장).
- 읽을 때 `index` 의 역색인을 그대로 쓴다(다시 분석하지 않아 빠르다). 그래서 분석 규칙이 바뀐 findex 로
  올린 뒤에는 `reindex` 를 한 번 돌려야 옛 문서에도 새 규칙이 적용된다.
- 옛 **버전 1** 파일도 읽는다(쓰지는 않는다):
  `{"version": 1, "next_id": 3, "docs": {"1": {"title": "...", "text": "본문", "tags": "a,b", "date": "2024-01-31"}}}`
  — 설정은 기본값, 태그는 쉼표로 이은 문자열, 역색인은 문서로 다시 만든다.
- 깨진 파일, 지원하지 않는 형식은 `StorageError`.
- 쓰기는 임시 파일에 쓴 뒤 `os.replace` 로 바꿔 넣는다.

## CLI

```
python -m findex [--index 파일] 명령 ...      # 기본 파일 findex.json, 없으면 빈 색인으로 시작
```

| 명령 | 출력 |
|---|---|
| `add 제목 [--body 본문 \| --body-file 파일] [--tag 태그]... [--date YYYY-MM-DD]` | 새 id |
| `import 파일.jsonl` | 한 줄에 문서 하나(`{"title", "body", "tags", "date"}`). 새 id 를 한 줄에 하나씩. 하나라도 틀리면 아무것도 넣지 않는다 |
| `export 파일.jsonl` | `내보냄: N` |
| `merge 다른색인.json` | 그 색인의 문서를 새 id 로 모두 추가, 새 id 를 한 줄에 하나씩 |
| `update ID [--title ..] [--body .. \| --body-file ..] [--tag ..]... [--clear-tags] [--date ..]` | 없음 |
| `delete ID` | 없음 |
| `get ID [--highlight 검색어]` | `id: 1` / `title: ...` / `tags: a, b`(없으면 `-`) / `date: ...`(없으면 `-`) / 빈 줄 / 본문. `--highlight` 면 제목과 본문에 강조 표시 |
| `terms [--field title\|body] [--limit N]` | `색인어<TAB>문서 수` |
| `search 검색어 [--page N] [--per-page N] [--sort score\|date] [--snippets] [--json]` | 첫 줄 `검색 결과 N건`, 그다음 한 줄에 `ID<TAB>점수(소수 4자리)<TAB>제목`. `--snippets` 면 각 결과 아래에 4칸 들여 쓴 스니펫 한 줄. `--json` 이면 `{"total", "page", "per_page", "hits": [{"id", "score", "title"}]}` 한 줄(점수 반올림 없음) |
| `facets [검색어] [--limit N]` | `이름<TAB>개수` |
| `suggest 접두어 [--limit N]` | `색인어<TAB>문서 수` |
| `similar ID [--limit N]` | `ID<TAB>점수<TAB>제목` |
| `explain ID 검색어` | `필드<TAB>조각<TAB>점수` |
| `correct 검색어` | 고친 검색어 한 줄 (고칠 것이 없으면 출력 없음) |
| `reindex` | `다시 색인함: N` (저장한다) |
| `check` | 문제를 한 줄에 하나씩(종료 코드 1), 없으면 `OK` |
| `parse 검색어` | 검색어를 어떻게 읽었는지 (디버깅용, 형식이 바뀔 수 있음) |
| `info` | `stopwords<TAB>default 또는 단어 수` / `stem<TAB>yes 또는 no` / `boosts<TAB>title=2 body=1` |
| `stats` | `documents<TAB>N` / `terms<TAB>N` / `next_id<TAB>N` |

- 바꾸는 명령(add, import, merge, update, delete, reindex)만 저장한다. 출력은 UTF-8.
- 오류는 표준 오류에 `오류: <메시지>`, 종료 코드 1, 파일은 바꾸지 않는다.
