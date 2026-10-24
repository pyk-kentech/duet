"""검색 도우미: 자동 완성과 철자 교정.

**자동 완성** (``Index.suggest``, README 의 "자동 완성" 절): ``title``·``body`` 의 색인어(어간
형태) 중 접두어로 시작하는 것과 그 색인어가 있는 문서 수. 문서 수 내림차순, 같으면 색인어 순.

**철자 교정** (``Index.correct``, README 의 "철자 교정" 절): 검색어의 단어 중 색인에 없는 것을
편집 거리(글자 넣기·빼기·바꾸기, 이웃한 두 글자 맞바꾸기) 2 이하인 색인어 중 가장 가까운 것으로
바꾼 검색어를 돌려준다. 가까움은 거리 → 문서 수(많은 것) → 색인어 순. 바꿀 것이 없으면 ``None``.

* 연산자(``AND``/``OR``/``NOT``), 필드가 붙은 단어(``x:y``), 접두어(``*``), 구절(따옴표),
  괄호가 붙은 단어, ``-`` 로 시작하는 단어는 건드리지 않는다.
* 글자로만 된 4글자 이상 단어만 고친다. 고친 단어는 색인어(어간 형태)로 바뀐다.
"""

from __future__ import annotations

from findex.analyzer import Analyzer
from findex.index import TEXT_FIELDS, InvertedIndex

MAX_DISTANCE = 2
MIN_CORRECT_LENGTH = 4
_OPERATORS = frozenset({"AND", "OR", "NOT"})


# ====================================================================== suggest
def suggest_terms(index: InvertedIndex, prefix: str, limit: int = 10) -> list[tuple[str, int]]:
    """``prefix`` 로 시작하는 색인어와 문서 수 (``Index.suggest`` 의 본체)."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError(f"limit 은 1 이상의 정수여야 합니다: {limit!r}")
    p = prefix.strip().lower()
    if not p:
        return []
    found: dict[str, set[int]] = {}
    for f in TEXT_FIELDS:
        for term in index.terms(f):
            if term.startswith(p):
                found.setdefault(term, set()).update(index.postings(f, term))
    items = sorted(((t, len(ds)) for t, ds in found.items()), key=lambda x: (-x[1], x[0]))
    return items[:limit]


# ====================================================================== spelling
def edit_distance(a: str, b: str, limit: int = MAX_DISTANCE) -> int:
    """제한된 Damerau-Levenshtein(OSA) 거리. ``limit`` 을 넘으면 ``limit + 1``."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2: list[int] | None = None
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        best = cur[0]
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if (prev2 is not None and i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]):
                cur[j] = min(cur[j], prev2[j - 2] + 1)
            best = min(best, cur[j])
        if best > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[-1] if prev[-1] <= limit else limit + 1


def _doc_freqs(index: InvertedIndex) -> dict[str, int]:
    docs: dict[str, set[int]] = {}
    for f in TEXT_FIELDS:
        for term in index.terms(f):
            docs.setdefault(term, set()).update(index.postings(f, term))
    return {t: len(ds) for t, ds in docs.items()}


def _correctable(word: str) -> bool:
    if word in _OPERATORS or ":" in word or word.endswith("*"):
        return False
    if word.startswith(("-", '"', "(")) or word.endswith(('"', ")")):
        return False
    return len(word) >= MIN_CORRECT_LENGTH and word.isalpha()


def correct_query(query: str, index: InvertedIndex, analyzer: Analyzer) -> str | None:
    """철자를 고친 검색어 (바꿀 것이 없으면 ``None``)."""
    freqs: dict[str, int] | None = None
    out: list[str] = []
    changed = False
    for word in query.split():
        if not _correctable(word):
            out.append(word)
            continue
        terms = analyzer.query_terms(word)
        if len(terms) != 1 or any(index.has_term(f, terms[0]) for f in TEXT_FIELDS):
            out.append(word)
            continue
        if freqs is None:
            freqs = _doc_freqs(index)
        target = terms[0]
        best: tuple[int, int, str] | None = None
        for term, df in freqs.items():
            d = edit_distance(target, term)
            if d > MAX_DISTANCE:
                continue
            key = (d, -df, term)
            if best is None or key < best:
                best = key
        if best is None:
            out.append(word)
            continue
        out.append(best[2])
        changed = True
    return " ".join(out) if changed else None
