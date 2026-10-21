이 작업 폴더에는 기존 프로젝트 `findex`(표준 라이브러리만 쓰는 작은 전문 검색 라이브러리 + CLI)가 있다. 아래 백로그의 티켓 7개(FX-101 ~ FX-107)를 **모두** 처리한다.

- 티켓이 바꾸라고 한 것 말고는 기존 동작을 바꾸지 않는다. README.md 와 코드의 docstring 에 적힌 동작도 기존 동작이다(테스트가 없는 동작도 포함).
- 공개 이름(`findex` 패키지에서 import 하는 이름, `Index` 의 메서드와 인자), CLI 명령·인자·출력 형식은 티켓이 바꾸라고 한 것 말고는 그대로 둔다.
- 패키지는 작업 폴더 최상위의 `findex/` 다(src 레이아웃 아님). Python 3.11+, 표준 라이브러리만 쓴다.
- 테스트도 함께 작성한다. 기존 테스트(`tests/`)는 계속 통과해야 한다.
- README.md 와 DESIGN.md 를 바뀐 동작에 맞게 고친다.

---

## FX-101 악센트 있는 글자로 찾을 수 없다 (버그)

> `Café` 로 넣은 문서가 `cafe` 로 안 찾아진다. 찾은 다음에도 강조가 안 되고, facets 에는 `Café` 와 `cafe` 가 따로 나온다. 원문이 분해형(NFD)으로 들어온 문서는 `naïve` 로도 `naive` 로도 안 찾아진다.

기대 동작

- 문자 비교의 정규형을 하나로 정한다: **NFKD 분해 → 결합 표시(유니코드 범주 `Mn`) 제거 → casefold → NFC**.
  예: `Café` = `cafe`, `naïve` = `naive`, `Ångström` = `angstrom`, `Straße` = `strasse`, `ﬁle`(합자 U+FB01) = `file`, `ＰＹＴＨＯＮ`(전각) = `python`. 한글은 그대로다(`한국어` 는 `한국어`, `한국*` 로 찾힌다).
- 원문이 분해형(NFD)이어도 같다. 단어 안의 결합 표시는 단어를 가르지 않는다: `naïve` 는 한 단어이고 `naive` 로 찾힌다.
- 이 정규형이 쓰이는 곳: 색인과 검색어(단어, 구절, 필드 검색, 접두어), 불용어 비교(`Index(stopwords=["für"])` 면 `fur` 도 불용어), 강조·스니펫, `tag:` 필터, facets(같은 태그로 묶기와 같은 개수일 때의 이름 순서), 한 문서 안 태그의 중복 제거(`["Café", "cafe"]` → `("Café",)`), 자동 완성(`suggest`)의 접두어.
- 원문은 바꾸지 않는다: `get()`·`documents()`·CLI `get`·`export`·저장 파일의 문서는 넣은 철자 그대로다. facets 의 이름은 지금 규칙(그 태그를 가진 문서 중 id 가 가장 작은 문서의 철자) 그대로다.
- 강조는 원문 철자에, 원문 단어 전체를 감싼다: `Crème brûlée` 를 `creme` 로 찾으면 `[Crème] brûlée`, NFD `naïve` 는 결합 표시까지 포함해 `[naïve]`, `Die Straße und das Café` 를 `strasse cafe` 로 찾으면 `Die [Straße] und das [Café]`.
- 자동 완성 결과는 지금처럼 색인어(정규형) 그대로: `suggest("CAFÉ")` → `[("cafe", 문서 수), ...]`.

## FX-102 하이픈으로 이은 단어 (기능 요청)

> `e-mail` 이 든 문서가 `email` 로 안 찾아지고, `email` 이라고 쓴 문서는 `e-mail` 로 안 찾아진다.

기대 동작

- **하이픈 단어**: 단어 글자 사이에 하이픈(`-`, U+002D) 하나가 낀 것. 여러 번 이어져도 된다(`state-of-the-art`). 하이픈이 둘 이상 붙어 있거나(`a--b`) 단어 앞뒤에 있으면(`-x`, `x-`) 지금처럼 단순히 가른다.
- 색인: 하이픈 단어는 **조각들**(`e`, `mail`)과 **합친 형태**(`email`) 모두로 색인한다. 조각과 합친 형태 모두 정규화·불용어·어간 규칙을 똑같이 거친다. 예: `e-mails` → 합친 형태 `email`, 조각 `e`, `mail`. `state-of-the-art` → 합친 형태 `stateoftheart`, 조각 `state`, `art`(`of`, `the` 는 불용어).
- 위치: 조각들은 지금처럼 차례로 위치를 차지하고(불용어 조각은 위치를 차지하지 않는다), 합친 형태는 **첫 조각과 같은 위치**에 둔다. 그래서 `send e-mail address` 에 구절 `"e mail"`, `"send e-mail"`, `"send email"`, `"e-mail address"`, `"mail address"` 가 모두 맞는다.
- 필드 길이(BM25 의 `len`·`avglen`)는 조각만 센다(합친 형태는 세지 않는다). 그래서 본문이 `e-mail` 인 문서와 `e mail` 인 문서는 `mail` 검색에서 점수가 같다.
- 따옴표 밖 검색어의 하이픈 단어는 **합친 형태 하나**로 찾는다(지금처럼 구절로 바꾸지 않는다): `e-mail` = `email`, `title:x-ray` = `title:xray`. 구절 안의 하이픈 단어는 조각들로 본다: `"send e-mail"` = `"send e mail"`.
- `-단어`(NOT 줄임) 규칙은 그대로다. 토큰 맨 앞의 하이픈만 NOT 이다: `e -mail` 은 `e AND NOT mail`, `-e-mail` 은 `NOT email`.
- 강조: 합친 형태로 맞으면 하이픈 단어 전체만 감싸고(`email` 로 찾으면 `[e-mail]`), 아니면 맞은 조각만 감싼다(`mail` 로 찾으면 `e-[mail]`).
- 그 밖의 문장부호 규칙은 그대로다: `foo.bar`, `x/y` 는 가르고, 검색어에서는 그 색인어들의 구절로 찾는다.

## FX-103 update 뒤에도 옛 내용으로 찾아진다 (버그)

> 본문을 update 로 바꿨는데 지운 단어로 아직 찾아지고, 남아 있는 단어의 점수는 오히려 올라갔다. 태그를 바꿔도 `tag:` 옛 태그로 걸린다. 그리고 update 로 날짜를 지울 방법이 없다.

기대 동작

- update 뒤의 검색 결과·점수·`tag:` 필터·facets·강조·스니펫·자동 완성은, 처음부터 바뀐 내용으로 넣은 색인과 같다(같은 문서들을 같은 id 로 넣은 색인과 점수까지 같다).
- id 는 그대로다. 문서 수와 다음에 붙을 id(`next_id`)도 update 때문에 바뀌지 않는다.
- 새 기능: `update(doc_id, date="")` 는 날짜를 지운다(`None` 은 지금처럼 '그대로 둔다'). CLI `update ID --date ""` 도 같다.
- 지운 문서·없는 문서의 update 는 지금처럼 `DocumentNotFound`, 잘못된 값(빈 제목 등)은 `ValueError` 이고 문서는 그대로 남는다.

## FX-104 동의어 (기능 요청)

> `car` 로 찾으면 `automobile` 이라고 쓴 문서도 나왔으면 좋겠다.

기대 동작

- `Index.add_synonyms(*words) -> None`: 단어들을 한 동의어 묶음으로 등록한다. 각 단어는 색인과 같은 분석(정규화·어간, 하이픈 단어는 합친 형태)을 거쳐 **색인어 하나**가 되어야 한다. 색인어가 서로 다른 단어가 2개 미만이거나, 어떤 단어가 색인어 하나가 되지 않으면(빈 문자열, 불용어, `machine learning` 처럼 여러 단어) `ValueError` 이고 아무것도 등록하지 않는다.
- 묶음은 양방향이다: 묶음의 어느 단어로 찾든 묶음의 모든 단어에 맞는다. 새 묶음이 기존 묶음들과 색인어를 하나라도 공유하면 하나로 합친다.
- `Index.synonyms() -> list[list[str]]`: 등록한 철자 그대로. 묶음은 처음 등록한 순서, 묶음 안의 단어도 등록 순서. 합친 묶음은 가장 앞 묶음의 자리에 두고, 단어는 기존 묶음들의 단어(묶음 순서대로) 다음에 새 단어. 색인어가 같은 단어(예: `Car` 와 `cars`)는 처음 것만 남긴다. 예: `add_synonyms("car", "auto")`, `add_synonyms("bike", "bicycle")`, `add_synonyms("auto", "Automobile", "cars")` → `[["car", "auto", "Automobile"], ["bike", "bicycle"]]`.
- 검색: 따옴표 밖의 단어(필드 검색 포함)는 묶음의 색인어들의 OR 처럼 찾고, 점수도 동의어가 없을 때의 그 OR 와 같다(`car` 의 점수 = 동의어 없는 색인에서 `car OR automobile OR auto` 의 점수). NOT 아래에서도 확장한다(`vehicle -car` 는 `automobile` 문서도 뺀다). 접두어(`ca*`), `tag:`, `date:` 는 확장하지 않는다.
- 문서를 다시 색인하지 않고 검색할 때 적용한다. 묶음을 문서보다 먼저 등록하든 나중에 등록하든 결과가 같다. `count`, `facets(query)` 도 같은 검색 결과를 쓴다.
- CLI: `synonyms add 단어 단어 [단어...]`(저장한다, 출력 없음), `synonyms list`(한 줄에 묶음 하나, 단어를 `, ` 로 이어서). 오류는 다른 명령처럼 `오류: ...`, 종료 코드 1.
- 저장은 FX-105 를 따른다.

## FX-105 저장 형식 버전 3 (기능 요청 + 버그)

> 색인 파일이 너무 크다(역색인을 통째로 저장한다). 그리고 다음 버전 프로그램이 쓴 파일(버전 4)을 지금 프로그램이 조용히 읽어서 이상한 결과를 낸다.

기대 동작

- `save` 는 항상 **버전 3** 으로 쓴다:
  `{"format": "findex", "version": 3, "settings": {"stopwords": ..., "stem": ..., "boosts": {...}, "synonyms": [[...], ...]}, "next_id": N, "documents": [...]}`.
  `settings` 의 `stopwords`·`stem`·`boosts` 와 `documents` 의 각 문서는 버전 2 와 같다. `synonyms` 는 `Index.synonyms()` 와 같은 값. 역색인(버전 2 의 `index`)은 저장하지 않는다.
- `load` 는 버전 1, 2, 3 을 읽는다. 읽을 때는 언제나 문서로부터 역색인을 다시 만든다: 옛 파일의 문서도 지금 분석 규칙(FX-101, FX-102)으로 찾아져야 한다. 버전 2 의 설정과 `index.next_id`, 버전 1 의 `next_id` 는 지킨다(지운 id 를 다시 쓰지 않는다).
- 그 밖의 `version`(4 이상, 0, 없음, 정수가 아닌 값)은 `StorageError` 이고 메시지에 그 값을 넣는다. 버전 2·3 인데 `format` 이 `"findex"` 가 아니어도 `StorageError`.
- CLI 는 옛 파일로 일할 수 있고, 바꾸는 명령을 하면 버전 3 으로 다시 쓴다. 읽을 수 없는 파일이면 `오류: ...`, 종료 코드 1, 파일은 그대로 둔다.

## FX-106 큰 색인에서 너무 느리다 (성능)

> 문서 3만 개를 넣는 데 몇 분이 걸린다. 지우기·고치기·접두어 검색·NOT 검색·자동 완성·불러오기도 문서 수에 비해 너무 느리다.

아래 함수로 만든 문서 30,000개(`docs = make_docs()`)를 `Index()` 에 `add(**d)` 로 하나씩 넣은 색인으로 잰다. 각 항목은 따로 잰 시간이다(보통 노트북 기준). 결과는 지금 규칙대로 정확해야 한다.

```python
import random

SYLLABLES = ["ka", "lo", "mi", "ne", "ru", "sa", "to", "vi", "pe", "zu", "ba", "do", "fe", "gi", "ho", "ju"]

def make_docs(n=30000):
    rng = random.Random(2026)

    def word():
        return "".join(rng.choice(SYLLABLES) for _ in range(rng.randrange(2, 5)))

    docs = []
    for i in range(n):
        body = " ".join(word() for _ in range(5)) + (" common" if i % 3 == 0 else "")
        docs.append({"title": f"{word()} {word()}", "body": body, "tags": [f"tag{rng.randrange(50)}"],
                     "date": f"{rng.randrange(2010, 2025)}-{rng.randrange(1, 13):02d}-{rng.randrange(1, 29):02d}"})
    return docs
```

| 작업 | 제한 |
|---|---|
| 30,000개 `add` (하나씩) | 10초 |
| id 가 1, 4, 7, … 인 문서 10,000개 `delete` | 1.5초 |
| id 가 2, 8, 14, … 인 문서 5,000개 `update(id, body="changed common words here")` | 1.5초 |
| `search("ka*")`, `search("lo*")` 처럼 첫 음절 10개(`SYLLABLES[:10]`)의 접두어 검색을 두 바퀴(20번) | 2초 |
| `search("-common")` 20번 | 2초 |
| `suggest(a + b[0])` (`a` 는 `SYLLABLES` 의 16개, `b` 는 `SYLLABLES` 의 앞 13개) 208번 × 5바퀴 = 1,040번 | 1.5초 |
| `save` 한 뒤 `Index.load` | 8초 |

## FX-107 동의어가 구절과 강조에서 안 된다 (FX-104 후속)

> `car` 를 `automobile` 의 동의어로 등록했는데 `"fast car"` 로는 `fast automobile` 문서가 안 나온다. `car` 로 찾은 결과에서 `automobile` 이 강조되지 않는다.

기대 동작

- 구절(따옴표 안, `title:"..."` 같은 필드 구절, 문장부호 때문에 구절이 된 단어 모두)의 각 자리도 동의어 묶음으로 확장한다: `"fast car"` 는 `fast automobile` 에, `"red car wash"` 는 `red auto wash` 에 맞는다. 구절의 tf 는 (어느 동의어 조합이든) 구절이 나온 횟수, df 는 그런 구절이 있는 문서 수.
- 강조·스니펫: 동의어로 맞은 단어도 강조한다(`car` 로 찾으면 `[automobile]` 도). 구절의 단어도 동의어까지 각각 강조한다(구절로 붙어 있지 않아도 강조하는 기존 규칙 그대로). 접두어는 확장하지 않는다.
- FX-101·FX-102 와 함께 동작한다: 동의어 단어의 악센트·대소문자는 정규형으로 비교하고(`add_synonyms("café", "coffeehouse")` 면 `cafe` 로 `coffeehouse` 문서가 찾힌다), 하이픈 단어는 합친 형태다(`add_synonyms("e-mail", "message")` 면 `message` 로 `e-mail` 문서가 찾히고 강조는 `[e-mail]`).
