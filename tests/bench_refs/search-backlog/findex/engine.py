"""``Index``: findex 의 공개 API.

문서 저장소 + 역색인 + 통계를 묶는다. 다른 모듈은 이 클래스를 통해 쓴다.

id 규칙 (README 에 적힌 동작):

* id 는 1 부터 차례로 붙는 정수다.
* **지운 문서의 id 는 다시 쓰지 않는다.** 다음 id 는 지금까지 붙인 가장 큰 id + 1 이다.
  가장 마지막 문서를 지워도 그렇고, 저장했다가 다시 읽어도 그렇다.
* ``update`` 는 id 를 바꾸지 않는다. 바뀐 문서는 옛 색인 흔적을 모두 지우고 다시 색인한다.

조회 함수(``get``, ``update``, ``delete``)에 없는 id 나 지운 id 를 주면
:class:`~findex.errors.DocumentNotFound`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from findex.analyzer import Analyzer
from findex.document import Document, make_document, read_jsonl, validate_items, write_jsonl
from findex.errors import DocumentNotFound
from findex.facets import tag_facets
from findex.highlight import DEFAULT_MARKERS, SNIPPET_LENGTH, build_matcher, check_markers, find_spans, mark, snippet
from findex.index import TAG_FIELD, TEXT_FIELDS, InvertedIndex
from findex.query import parse
from findex.scoring import CorpusStats, check_boosts
from findex.search import Hit, SearchResults, Searcher, check_paging, explain_scores, order, paginate, top_terms
from findex.suggest import correct_query, suggest_terms
from findex.synonyms import SynonymTable
from findex.textutil import tag_key

__all__ = ["Index", "Hit", "SearchResults"]

SIMILAR_TERMS = 10


class Index:
    """검색 색인.

    ``stopwords``: ``None`` 이면 기본 영어 불용어, 아니면 그 목록으로 바꾼다.
    ``stem``: 어간 추출 여부. ``boosts``: 필드 가중치(``{"title": 2.0, "body": 1.0}`` 이 기본).
    """

    def __init__(self, *, stopwords: Iterable[str] | None = None, stem: bool = True,
                 boosts: dict[str, float] | None = None):
        self.analyzer = Analyzer(stopwords=stopwords, stem=stem)
        self.boosts = check_boosts(boosts)
        self._docs: dict[int, Document | None] = {}      # None = deleted (id stays reserved)
        self._next_id = 1
        self._live = 0
        self._index = InvertedIndex()
        self._stats = CorpusStats()
        self._synonyms = SynonymTable()

    # ================================================================== documents
    def add(self, title: str, body: str = "", tags: Iterable[str] | None = (), date: str | None = None) -> int:
        """문서를 넣고 새 id 를 돌려준다."""
        doc = make_document(self._next_id, title, body, tags, date)
        self._next_id += 1
        self._docs[doc.id] = doc
        self._live += 1
        self._index_document(doc)
        self._stats.add_doc(self._index, doc.id)
        return doc.id

    def add_many(self, items: Iterable[dict]) -> list[int]:
        """여러 문서를 한꺼번에 넣는다. 전부 아니면 전무: 하나라도 틀리면 아무것도 넣지 않는다.

        ``items`` 의 각 항목은 ``title``(필수), ``body``, ``tags``, ``date`` 키를 가진 dict.
        틀린 항목이 있으면 ``ValueError`` (메시지에 몇 번째 항목인지 1 부터 센 번호).
        """
        checked = validate_items(items)
        return [self.add(**fields) for fields in checked]

    def merge(self, other: "Index") -> list[int]:
        """다른 색인의 (지우지 않은) 문서를 id 순으로 모두 이 색인에 새 id 로 넣는다.

        분석 설정·가중치는 이 색인 것을 쓴다(``other`` 의 설정은 무시). 넣은 새 id 목록을 돌려준다.
        ``other`` 는 바뀌지 않는다. 자기 자신을 합치면 ``ValueError``.
        """
        if other is self:
            raise ValueError("자기 자신은 합칠 수 없습니다")
        items = [{"title": d.title, "body": d.body, "tags": list(d.tags), "date": d.date} for d in other.documents()]
        return self.add_many(items)

    def update(self, doc_id: int, *, title: str | None = None, body: str | None = None,
               tags: Iterable[str] | None = None, date: str | None = None) -> Document:
        """문서의 일부 필드를 바꾼다. ``None`` 인 인자는 그대로 둔다. ``date=""`` 는 날짜를 지운다.

        id 는 바뀌지 않는다. 검색·점수·필터는 처음부터 바뀐 내용으로 넣은 것과 같아진다.
        """
        old = self._require(doc_id)
        if date is None:
            new_date = old.date
        elif date == "":
            new_date = None
        else:
            new_date = date
        new = make_document(
            doc_id,
            old.title if title is None else title,
            old.body if body is None else body,
            old.tags if tags is None else tags,
            new_date,
        )
        self._stats.remove_doc(self._index, doc_id)
        self._index.remove_document(doc_id)
        self._docs[doc_id] = new
        self._index_document(new)
        self._stats.add_doc(self._index, doc_id)
        return new

    def delete(self, doc_id: int) -> None:
        """문서를 지운다. id 는 다시 쓰지 않는다."""
        self._require(doc_id)
        self._docs[doc_id] = None
        self._live -= 1
        self._stats.remove_doc(self._index, doc_id)
        self._index.remove_document(doc_id)

    def get(self, doc_id: int) -> Document:
        return self._require(doc_id)

    def documents(self) -> list[Document]:
        """지우지 않은 문서들 (id 순)."""
        return [d for _, d in sorted(self._docs.items()) if d is not None]

    def ids(self) -> list[int]:
        return [d.id for d in self.documents()]

    def __len__(self) -> int:
        return self._live

    def __contains__(self, doc_id: object) -> bool:
        return isinstance(doc_id, int) and self._docs.get(doc_id) is not None

    @property
    def next_id(self) -> int:
        """다음에 ``add`` 가 붙일 id."""
        return self._next_id

    # ================================================================== search
    def search(self, query: str, *, page: int = 1, per_page: int = 10, sort: str = "score") -> SearchResults:
        """검색. 결과는 한 페이지(``page`` 는 1 부터). 페이지가 범위를 넘으면 빈 목록."""
        check_paging(page, per_page)
        scores = self._evaluate(query)
        ids = order(scores, self._docs, sort)
        return paginate(ids, scores, self._docs, page, per_page)

    def count(self, query: str) -> int:
        return len(self._evaluate(query))

    def facets(self, query: str | None = None, *, limit: int | None = None) -> list[tuple[str, int]]:
        """태그별 문서 수. ``query`` 를 주면 그 검색에 맞은 문서들만 센다."""
        if query is None:
            docs = self.documents()
        else:
            docs = [self._docs[d] for d in self._evaluate(query)]
        return tag_facets(docs, limit)

    def highlight(self, doc_id: int, query: str, *, field: str = "title",
                  markers: tuple[str, str] = DEFAULT_MARKERS) -> str:
        """문서 필드 전체에 강조 표시를 넣어 돌려준다."""
        if field not in TEXT_FIELDS:
            raise ValueError(f"강조할 수 없는 필드입니다: {field}")
        markers = check_markers(markers)
        doc = self._require(doc_id)
        text = getattr(doc, field)
        matcher = build_matcher(parse(query), self.analyzer, field, self._synonyms.expand)
        return mark(text, find_spans(text, matcher), markers)

    def snippet(self, doc_id: int, query: str, *, length: int = SNIPPET_LENGTH,
                markers: tuple[str, str] = DEFAULT_MARKERS) -> str:
        """본문 스니펫 (강조 포함)."""
        markers = check_markers(markers)
        doc = self._require(doc_id)
        matcher = build_matcher(parse(query), self.analyzer, "body", self._synonyms.expand)
        return snippet(doc.body, find_spans(doc.body, matcher), length, markers)

    def suggest(self, prefix: str, *, limit: int = 10) -> list[tuple[str, int]]:
        """자동 완성: ``prefix`` 로 시작하는 색인어와 그 단어가 있는 문서 수.

        ``title``·``body`` 의 색인어(정규형·어간 형태)에서 찾는다. 문서 수 내림차순, 같으면 단어순.
        ``prefix`` 도 정규형으로 비교한다.
        """
        return suggest_terms(self._index, prefix, limit)

    def correct(self, query: str) -> str | None:
        """철자를 고친 검색어 ("혹시 이것을 찾으셨나요?"). 고칠 것이 없으면 ``None``."""
        return correct_query(query, self._index, self.analyzer)

    def similar(self, doc_id: int, *, limit: int = 5) -> list[Hit]:
        """비슷한 문서: 그 문서에서 tf-idf 가 큰 색인어 10개로 OR 검색한 결과 (자기 자신 제외)."""
        doc = self._require(doc_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError(f"limit 은 1 이상의 정수여야 합니다: {limit!r}")
        terms = top_terms(self, doc, SIMILAR_TERMS)
        searcher = self._searcher()
        scores: dict[int, float] = {}
        for term in terms:
            for d, s in searcher._score_term(term, TEXT_FIELDS).items():
                if d != doc.id:
                    scores[d] = scores.get(d, 0.0) + s
        ids = order(scores, self._docs, "score")[:limit]
        return [Hit(d, scores[d], self._docs[d].title) for d in ids]

    def explain(self, doc_id: int, query: str) -> list[tuple[str, str, float]]:
        """점수 풀이(디버깅용): ``(필드, 검색어 조각, 점수)`` 목록. 형식은 바뀔 수 있다."""
        doc = self._require(doc_id)
        return explain_scores(self._searcher(), parse(query), doc.id)

    # ================================================================== synonyms
    def add_synonyms(self, *words: str) -> None:
        """동의어 묶음 등록 (README 의 "동의어" 절). 틀리면 ``ValueError``, 아무것도 바꾸지 않는다."""
        self._synonyms.add(words, self.analyzer)

    def synonyms(self) -> list[list[str]]:
        """등록한 동의어 묶음 (등록한 철자 그대로)."""
        return self._synonyms.groups()

    def stats(self) -> dict[str, int]:
        return {"documents": len(self), "terms": self._index.term_count(), "next_id": self._next_id}

    def vocabulary(self, *, field: str | None = None, limit: int = 20) -> list[tuple[str, int]]:
        """가장 많은 문서에 나온 색인어들: ``[(색인어, 문서 수)]``, 문서 수 내림차순, 같으면 색인어 순.

        ``field`` 가 ``None`` 이면 ``title``·``body`` 를 합쳐(한 문서는 한 번) 센다.
        """
        if field is not None and field not in TEXT_FIELDS:
            raise ValueError(f"색인어를 볼 수 없는 필드입니다: {field}")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError(f"limit 은 1 이상의 정수여야 합니다: {limit!r}")
        fields = (field,) if field else TEXT_FIELDS
        docs: dict[str, set[int]] = {}
        for f in fields:
            for term in self._index.terms(f):
                docs.setdefault(term, set()).update(self._index.postings(f, term))
        ranked = sorted(((t, len(ds)) for t, ds in docs.items()), key=lambda x: (-x[1], x[0]))
        return ranked[:limit]

    def check(self) -> list[str]:
        """색인이 문서와 맞는지 검사한다(고장 진단용). 문제를 사람이 읽을 문장으로 돌려준다(없으면 빈 목록).

        문서를 지금 설정으로 다시 분석한 결과와 역색인(위치), 필드 길이, 태그 색인, 통계, ``next_id`` 를 비교한다.
        """
        problems: list[str] = []
        live = {d.id: d for d in self.documents()}
        if live and self._next_id <= max(live):
            problems.append(f"next_id({self._next_id})가 가장 큰 id({max(live)})보다 크지 않습니다")
        for f in TEXT_FIELDS:
            expected: dict[tuple[str, int], list[int]] = {}
            for d in live.values():
                for t in self.analyzer.analyze(getattr(d, f)):
                    expected.setdefault((t.term, d.id), []).append(t.position)
            actual: dict[tuple[str, int], list[int]] = {}
            for term in self._index.terms(f):
                for doc_id, positions in self._index.postings(f, term).items():
                    actual[(term, doc_id)] = list(positions)
            for key in sorted(set(expected) | set(actual)):
                if expected.get(key) != actual.get(key):
                    problems.append(f"{f}: 문서 {key[1]} 의 {key[0]!r} 위치가 다릅니다 "
                                    f"(기대 {expected.get(key)}, 실제 {actual.get(key)})")
            for d in live.values():
                want = self.analyzer.length(getattr(d, f))
                if self._index.length(f, d.id) != want:
                    problems.append(f"{f}: 문서 {d.id} 의 길이가 다릅니다 (기대 {want}, 실제 {self._index.length(f, d.id)})")
        want_tags = {(k, d.id) for d in live.values() for k in self._tag_keys(d)}
        have_tags = {(k, doc_id) for k in self._index.terms(TAG_FIELD) for doc_id in self._index.postings(TAG_FIELD, k)}
        for key in sorted(want_tags ^ have_tags):
            problems.append(f"tags: 문서 {key[1]} 의 태그 {key[0]!r} 색인이 맞지 않습니다")
        if self._stats.doc_count != len(live):
            problems.append(f"통계의 문서 수({self._stats.doc_count})가 실제({len(live)})와 다릅니다")
        return problems

    def reindex(self) -> int:
        """문서로부터 역색인과 통계를 다시 만든다. 다시 색인한 문서 수를 돌려준다.

        저장 파일을 읽을 때는 언제나 다시 색인하므로(형식 버전 3) 보통은 필요 없다.
        """
        docs = self.documents()
        self._index = InvertedIndex()
        for d in docs:
            self._index_document(d)
        self._refresh_stats()
        return len(docs)

    # ================================================================== persistence
    def save(self, path: str | Path) -> None:
        from findex import storage
        storage.save(self, path)

    @classmethod
    def load(cls, path: str | Path) -> "Index":
        from findex import storage
        return storage.load(path)

    def import_jsonl(self, path: str | Path) -> list[int]:
        """JSON Lines 파일의 문서를 모두 넣는다(전부 아니면 전무). 새 id 목록."""
        return self.add_many(read_jsonl(path))

    def export_jsonl(self, path: str | Path) -> int:
        """지우지 않은 문서를 id 순으로 JSON Lines 파일에 쓴다. 쓴 문서 수."""
        return write_jsonl(self.documents(), path)

    # ================================================================== internals
    def _require(self, doc_id: object) -> Document:
        doc = self._docs.get(doc_id) if isinstance(doc_id, int) and not isinstance(doc_id, bool) else None
        if doc is None:
            raise DocumentNotFound(doc_id)
        return doc

    def _live_ids(self) -> list[int]:
        return [i for i, d in self._docs.items() if d is not None]

    def _live_docs(self) -> list[Document]:
        return [d for d in self._docs.values() if d is not None]

    def _index_document(self, doc: Document) -> None:
        for f in TEXT_FIELDS:
            self._index.add_field(doc.id, f, self.analyzer.analyze(getattr(doc, f)))
        self._index.add_tags(doc.id, self._tag_keys(doc))

    def _tag_keys(self, doc: Document) -> list[str]:
        """태그 색인에 넣는 키 (``tag:`` 필터가 찾는 값)."""
        return [tag_key(t) for t in doc.tags]

    def _refresh_stats(self) -> None:
        self._stats.refresh(self._index, self._live_ids())

    def _searcher(self) -> Searcher:
        return Searcher(self._index, self.analyzer, self._stats, self.boosts, self._live_docs, self._synonyms.expand)

    def _evaluate(self, query: str) -> dict[int, float]:
        node = parse(query)
        scores = self._searcher().evaluate(node)
        return scores or {}

    def _restore(self, docs: list[Document], next_id: int | None) -> None:
        """저장소에서 읽은 문서로 채운다. 역색인은 언제나 지금 분석 규칙으로 다시 만든다."""
        self._docs = {d.id: d for d in docs}
        self._live = len(self._docs)
        top = max(self._docs, default=0)
        self._next_id = max(int(next_id or 0), top + 1)
        self._index = InvertedIndex()
        for d in docs:
            self._index_document(d)
        self._refresh_stats()

    def __repr__(self) -> str:
        return f"Index(documents={len(self)}, next_id={self._next_id})"
