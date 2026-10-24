"""역색인 (inverted index).

필드마다 ``색인어 -> {문서 id: [위치, ...]}`` 를 둔다. 텍스트 필드는 ``title``, ``body``
이고, 태그는 따로 ``tags`` 필드에 **태그 하나를 통째로** 색인어로 넣는다(토큰으로 자르지
않는다, 위치는 태그 순번). 텍스트 필드는 BM25 를 위해 문서별 길이(색인어 수, 하이픈 단어의
합친 형태는 빼고)도 둔다.

문서별로 어떤 색인어를 넣었는지(정방향 색인)도 기억해서, 문서를 지울 때 그 문서의 색인어만
건드린다. 접두어 검색·자동 완성을 위해 필드별 정렬된 색인어 목록을 필요할 때 만들어 둔다.

이 클래스는 분석을 하지 않는다. 이미 분석된 ``(색인어, 위치)`` 를 받는다.
"""

from __future__ import annotations

from bisect import bisect_left
from typing import Iterable

from findex.analyzer import Term

#: 검색어가 필드를 정하지 않으면 찾는 텍스트 필드 (순서는 점수 합산 순서).
TEXT_FIELDS: tuple[str, ...] = ("title", "body")
TAG_FIELD = "tags"
ALL_FIELDS: tuple[str, ...] = (*TEXT_FIELDS, TAG_FIELD)

#: ``{문서 id: [위치, ...]}``. 위치는 분석기가 붙인 순번(불용어를 뺀 순서)이고 오름차순이다.
Postings = dict[int, list[int]]


class InvertedIndex:
    def __init__(self) -> None:
        self._postings: dict[str, dict[str, Postings]] = {f: {} for f in ALL_FIELDS}
        self._lengths: dict[str, dict[int, int]] = {f: {} for f in TEXT_FIELDS}
        self._doc_terms: dict[int, dict[str, set[str]]] = {}      # forward index
        self._sorted: dict[str, list[str] | None] = {f: None for f in ALL_FIELDS}

    # ------------------------------------------------------------------ write
    def _put(self, doc_id: int, field: str, term: str, position: int) -> None:
        table = self._postings[field]
        docs = table.get(term)
        if docs is None:
            docs = table[term] = {}
            self._sorted[field] = None
        docs.setdefault(doc_id, []).append(position)
        self._doc_terms.setdefault(doc_id, {}).setdefault(field, set()).add(term)

    def add_field(self, doc_id: int, field: str, terms: Iterable[Term]) -> None:
        """문서 하나의 한 필드를 넣는다. 같은 문서·필드를 다시 넣으면 위치가 덧붙는다."""
        count = 0
        for t in terms:
            self._put(doc_id, field, t.term, t.position)
            if not t.alias:
                count += 1
        if field in self._lengths:
            self._lengths[field][doc_id] = count

    def add_tags(self, doc_id: int, keys: Iterable[str]) -> None:
        """태그 키(정규화된 태그)를 넣는다."""
        for pos, key in enumerate(keys):
            self._put(doc_id, TAG_FIELD, key, pos)

    def remove_document(self, doc_id: int) -> None:
        """문서의 모든 흔적을 지운다 (그 문서의 색인어만 건드린다)."""
        for field, terms in self._doc_terms.pop(doc_id, {}).items():
            table = self._postings[field]
            for term in terms:
                docs = table.get(term)
                if docs is None:
                    continue
                docs.pop(doc_id, None)
                if not docs:
                    del table[term]
                    self._sorted[field] = None
        for lengths in self._lengths.values():
            lengths.pop(doc_id, None)

    def clear(self) -> None:
        self.__init__()

    # ------------------------------------------------------------------ read
    def postings(self, field: str, term: str) -> Postings:
        """``{문서 id: [위치]}`` (없으면 빈 dict). 돌려받은 값을 바꾸지 말 것."""
        return self._postings[field].get(term, {})

    def doc_freq(self, field: str, term: str) -> int:
        return len(self._postings[field].get(term, ()))

    def has_term(self, field: str, term: str) -> bool:
        return term in self._postings[field]

    def terms(self, field: str) -> list[str]:
        """필드의 색인어들 (순서 없음)."""
        return list(self._postings[field])

    def sorted_terms(self, field: str) -> list[str]:
        """필드의 색인어들 (사전순, 바뀔 때까지 재사용)."""
        cached = self._sorted[field]
        if cached is None:
            cached = self._sorted[field] = sorted(self._postings[field])
        return cached

    def terms_with_prefix(self, field: str, prefix: str) -> list[str]:
        """``prefix`` 로 시작하는 색인어 (사전순)."""
        terms = self.sorted_terms(field)
        out: list[str] = []
        for i in range(bisect_left(terms, prefix), len(terms)):
            if not terms[i].startswith(prefix):
                break
            out.append(terms[i])
        return out

    def length(self, field: str, doc_id: int) -> int:
        return self._lengths[field].get(doc_id, 0)

    def lengths(self, field: str) -> dict[int, int]:
        return self._lengths[field]

    def vocabulary(self) -> set[str]:
        """텍스트 필드 색인어 전체."""
        out: set[str] = set()
        for f in TEXT_FIELDS:
            out.update(self._postings[f])
        return out

    def term_count(self) -> int:
        return len(self.vocabulary())
