"""검색어 AST 를 색인에 대해 평가하고 점수를 매긴다.

평가 결과는 ``{문서 id: 점수}`` 다. 불용어뿐이라 아무 뜻이 없는 조각은 ``None`` 으로
돌려주고, 위쪽 AND/OR 는 ``None`` 을 건너뛴다(그래서 ``the cat`` 은 ``cat`` 과 같다).
검색어 전체가 ``None`` 이면 결과가 없다.

* 단어: 필드를 정하지 않으면 ``title`` 과 ``body`` 를 찾아 점수를 더한다(가중치 곱).
  단어 하나가 분석 후 여러 색인어가 되면(``foo.bar``, ``x/y`` 처럼 문장부호가 낀 경우)
  그 색인어들의 구절로 찾는다.
* 구절: 분석된 색인어들이 연속한 위치에 있어야 한다. tf 는 구절이 나온 횟수, df 는 구절이
  있는 문서 수로 BM25 를 구한다.
* 접두어: 필드의 색인어 중 접두어로 시작하는 것들을 **한 단어처럼** 점수 매긴다
  (tf 는 펼친 단어들의 tf 합, df 는 하나라도 가진 문서 수).
* ``tag:`` / ``date:`` 는 거르기만 하고 점수는 0 이다.
* AND 는 교집합(점수 합), OR 는 합집합(점수 합), NOT 은 전체 문서에서 뺀 것(점수 0).
  NOT 만 있는 검색어는 그것에 맞지 않는 모든 문서를 돌려준다.

예 (기본 설정)::

    apple pie          -> AND(apple, pie): 둘 다 있는 문서, 점수는 두 단어 점수의 합
    apple OR pear      -> 하나라도 있는 문서
    "apple pie"        -> 구절. 위치 p 에 apple, p+1 에 pie
    title:apple        -> title 필드만 (가중치 2.0)
    appl*              -> apple, applic(ation) ... 를 한 단어처럼
    -draft             -> draft 가 없는 모든 문서 (점수 0)
    the                -> 불용어뿐 -> 결과 없음

정렬·페이지는 :func:`order`, :func:`paginate` 가 한다. 점수가 같으면 id 가 작은 문서가 먼저다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable, Iterable

from findex.analyzer import Analyzer
from findex.document import Document
from findex.index import TAG_FIELD, TEXT_FIELDS, InvertedIndex
from findex.query import AndQ, DateQ, NotQ, OrQ, PhraseQ, PrefixQ, TagQ, TermQ, describe, iter_positive
from findex.scoring import CorpusStats, bm25, idf

Scores = dict[int, float]

SORTS = ("score", "date")
MAX_PER_PAGE = 100


@dataclass(frozen=True)
class Hit:
    doc_id: int
    score: float
    title: str

    def to_dict(self) -> dict:
        """CLI ``--json`` 용. 점수는 반올림하지 않는다."""
        return {"id": self.doc_id, "score": self.score, "title": self.title}


@dataclass
class SearchResults:
    """한 페이지의 결과. ``total`` 은 페이지와 상관없이 맞은 문서 전체 수."""

    total: int
    page: int
    per_page: int
    hits: list[Hit] = field(default_factory=list)

    @property
    def pages(self) -> int:
        return (self.total + self.per_page - 1) // self.per_page

    def ids(self) -> list[int]:
        return [h.doc_id for h in self.hits]

    def to_dict(self) -> dict:
        """CLI ``--json`` 출력: ``{"total", "page", "per_page", "hits": [...]}``."""
        return {"total": self.total, "page": self.page, "per_page": self.per_page,
                "hits": [h.to_dict() for h in self.hits]}

    def __iter__(self):
        return iter(self.hits)

    def __len__(self) -> int:
        return len(self.hits)


class Searcher:
    """색인 하나에 대한 평가기. 검색마다 새로 만든다(가볍다)."""

    def __init__(self, index: InvertedIndex, analyzer: Analyzer, stats: CorpusStats,
                 boosts: dict[str, float], live_docs: Callable[[], Iterable[Document]]):
        self.index = index
        self.analyzer = analyzer
        self.stats = stats
        self.boosts = boosts
        self.live_docs = live_docs

    # ------------------------------------------------------------------ dispatch
    def evaluate(self, node) -> Scores | None:
        if node is None:
            return None
        if isinstance(node, TermQ):
            return self._term(node)
        if isinstance(node, PhraseQ):
            return self._phrase(node.text, node.field)
        if isinstance(node, PrefixQ):
            return self._prefix(node)
        if isinstance(node, TagQ):
            return self._tag(node)
        if isinstance(node, DateQ):
            return self._date(node)
        if isinstance(node, AndQ):
            return self._and(node)
        if isinstance(node, OrQ):
            return self._or(node)
        if isinstance(node, NotQ):
            return self._not(node)
        raise TypeError(f"알 수 없는 검색어 노드: {node!r}")

    def _fields(self, field: str | None) -> tuple[str, ...]:
        return (field,) if field else TEXT_FIELDS

    # ------------------------------------------------------------------ leaves
    def _term(self, node: TermQ) -> Scores | None:
        terms = self.analyzer.query_terms(node.word)
        if not terms:
            return None
        if len(terms) > 1:
            return self._phrase_terms(terms, node.field)
        return self._score_term(terms[0], self._fields(node.field))

    def _score_term(self, term: str, fields: tuple[str, ...]) -> Scores:
        out: Scores = {}
        n = self.stats.doc_count
        for f in fields:
            postings = self.index.postings(f, term)
            if not postings:
                continue
            weight = self.boosts[f]
            avg = self.stats.avg_length(f)
            idf_value = idf(n, len(postings))
            for d, positions in postings.items():
                s = weight * bm25(len(positions), self.index.length(f, d), avg, idf_value)
                out[d] = out.get(d, 0.0) + s
        return out

    def _phrase(self, text: str, field: str | None) -> Scores | None:
        terms = self.analyzer.query_terms(text)
        if not terms:
            return None
        if len(terms) == 1:
            return self._score_term(terms[0], self._fields(field))
        return self._phrase_terms(terms, field)

    def _phrase_terms(self, terms: list[str], field: str | None) -> Scores:
        out: Scores = {}
        n = self.stats.doc_count
        for f in self._fields(field):
            lists = [self.index.postings(f, t) for t in terms]
            if any(not p for p in lists):
                continue
            candidates = set(lists[0]).intersection(*lists[1:])
            tfs: dict[int, int] = {}
            for d in candidates:
                later = [set(p[d]) for p in lists[1:]]
                count = 0
                for p0 in lists[0][d]:
                    if all((p0 + k + 1) in s for k, s in enumerate(later)):
                        count += 1
                if count:
                    tfs[d] = count
            if not tfs:
                continue
            weight = self.boosts[f]
            avg = self.stats.avg_length(f)
            idf_value = idf(n, len(tfs))
            for d, tf in tfs.items():
                out[d] = out.get(d, 0.0) + weight * bm25(tf, self.index.length(f, d), avg, idf_value)
        return out

    def expand_prefix(self, field: str, prefix: str) -> list[str]:
        """필드의 색인어 중 ``prefix`` 로 시작하는 것들 (사전순)."""
        return [t for t in sorted(self.index.terms(field)) if t.startswith(prefix)]

    def _prefix(self, node: PrefixQ) -> Scores:
        out: Scores = {}
        n = self.stats.doc_count
        for f in self._fields(node.field):
            terms = self.expand_prefix(f, node.prefix)
            if not terms:
                continue
            docs: list[int] = []
            tf: dict[int, int] = {}
            for t in terms:
                for d, positions in self.index.postings(f, t).items():
                    if d not in docs:
                        docs.append(d)
                    tf[d] = tf.get(d, 0) + len(positions)
            weight = self.boosts[f]
            avg = self.stats.avg_length(f)
            idf_value = idf(n, len(docs))
            for d in docs:
                out[d] = out.get(d, 0.0) + weight * bm25(tf[d], self.index.length(f, d), avg, idf_value)
        return out

    def _tag(self, node: TagQ) -> Scores:
        key = node.tag.strip().casefold()
        return {d: 0.0 for d in self.index.postings(TAG_FIELD, key)}

    def _date(self, node: DateQ) -> Scores:
        out: Scores = {}
        for doc in self.live_docs():
            value = doc.date_value()
            if value is None:
                continue
            if node.start is not None and value < node.start:
                continue
            if node.end is not None and value > node.end:
                continue
            out[doc.id] = 0.0
        return out

    # ------------------------------------------------------------------ combinators
    def _and(self, node: AndQ) -> Scores | None:
        result: Scores | None = None
        for item in node.items:
            part = self.evaluate(item)
            if part is None:
                continue
            if result is None:
                result = dict(part)
                continue
            result = {d: s + part[d] for d, s in result.items() if d in part}
        return result

    def _or(self, node: OrQ) -> Scores | None:
        result: Scores | None = None
        for item in node.items:
            part = self.evaluate(item)
            if part is None:
                continue
            if result is None:
                result = dict(part)
                continue
            for d, s in part.items():
                result[d] = result.get(d, 0.0) + s
        return result

    def _not(self, node: NotQ) -> Scores | None:
        part = self.evaluate(node.item)
        if part is None:
            return None
        excluded = list(part)
        return {doc.id: 0.0 for doc in self.live_docs() if doc.id not in excluded}


# ====================================================================== explain / similar
def explain_scores(searcher: Searcher, node, doc_id: int) -> list[tuple[str, str, float]]:
    """긍정 조각(단어·구절·접두어)마다, 필드마다 이 문서가 받은 점수."""
    out: list[tuple[str, str, float]] = []
    for leaf in iter_positive(node):
        for f in searcher._fields(leaf.field):
            part = searcher.evaluate(replace(leaf, field=f))
            if part and part.get(doc_id, 0.0) > 0.0:
                out.append((f, describe(replace(leaf, field=None)), part[doc_id]))
    return out


def top_terms(engine, doc: Document, k: int) -> list[str]:
    """문서에서 tf-idf 가 큰 색인어 ``k`` 개 (가중치 내림차순, 같으면 단어순)."""
    n = engine._stats.doc_count
    weights: dict[str, float] = {}
    for f in TEXT_FIELDS:
        tf: dict[str, int] = {}
        for t in engine.analyzer.analyze(getattr(doc, f)):
            tf[t.term] = tf.get(t.term, 0) + 1
        for term, count in tf.items():
            df = engine._index.doc_freq(f, term)
            weights[term] = weights.get(term, 0.0) + count * idf(n, df) * engine.boosts[f]
    ranked = sorted(weights, key=lambda t: (-weights[t], t))
    return ranked[:k]


# ====================================================================== ordering & paging
def check_paging(page: int, per_page: int) -> None:
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise ValueError(f"page 는 1 이상의 정수여야 합니다: {page!r}")
    if isinstance(per_page, bool) or not isinstance(per_page, int) or not 1 <= per_page <= MAX_PER_PAGE:
        raise ValueError(f"per_page 는 1~{MAX_PER_PAGE} 사이의 정수여야 합니다: {per_page!r}")


def order(scores: Scores, docs: dict[int, Document], sort: str) -> list[int]:
    """정렬된 문서 id. 점수순은 점수 내림차순 → id 오름차순, 날짜순은 최신 → 날짜 없음은 맨 뒤 → id."""
    if sort == "score":
        return sorted(scores, key=lambda d: (-scores[d], d))
    if sort == "date":
        def key(d: int):
            value = docs[d].date_value()
            return (value is None, -(value.toordinal() if value else 0), d)
        return sorted(scores, key=key)
    raise ValueError(f"정렬 방식은 {', '.join(SORTS)} 중 하나여야 합니다: {sort!r}")


def paginate(ids: list[int], scores: Scores, docs: dict[int, Document], page: int, per_page: int) -> SearchResults:
    start = (page - 1) * per_page
    chunk = ids[start:start + per_page]
    hits = [Hit(d, scores[d], docs[d].title) for d in chunk]
    return SearchResults(total=len(ids), page=page, per_page=per_page, hits=hits)
