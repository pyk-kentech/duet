"""역색인 (inverted index).

필드마다 ``색인어 -> {문서 id: [위치, ...]}`` 를 둔다. 텍스트 필드는 ``title``, ``body``
이고, 태그는 따로 ``tags`` 필드에 **태그 하나를 통째로** 색인어로 넣는다(토큰으로 자르지
않는다, 위치는 태그 순번). 텍스트 필드는 BM25 를 위해 문서별 길이(색인어 수)도 둔다.

이 클래스는 분석을 하지 않는다. 이미 분석된 ``(색인어, 위치)`` 를 받는다.
"""

from __future__ import annotations

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

    # ------------------------------------------------------------------ write
    def add_field(self, doc_id: int, field: str, terms: Iterable[Term]) -> None:
        """문서 하나의 한 필드를 넣는다. 같은 문서·필드를 다시 넣으면 위치가 덧붙는다."""
        table = self._postings[field]
        count = 0
        for t in terms:
            table.setdefault(t.term, {}).setdefault(doc_id, []).append(t.position)
            count += 1
        if field in self._lengths:
            self._lengths[field][doc_id] = count

    def add_tags(self, doc_id: int, keys: Iterable[str]) -> None:
        """태그 키(정규화된 태그)를 넣는다."""
        table = self._postings[TAG_FIELD]
        for pos, key in enumerate(keys):
            table.setdefault(key, {}).setdefault(doc_id, []).append(pos)

    def remove_document(self, doc_id: int) -> None:
        """문서의 모든 흔적을 지운다."""
        for field, table in self._postings.items():
            for term in list(table):
                docs = table[term]
                if doc_id in docs:
                    del docs[doc_id]
                    if not docs:
                        del table[term]
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

    # ------------------------------------------------------------------ persistence (format v2)
    def to_dict(self) -> dict:
        return {
            "fields": {f: {term: {str(d): pos for d, pos in docs.items()} for term, docs in table.items()}
                       for f, table in self._postings.items()},
            "lengths": {f: {str(d): n for d, n in lens.items()} for f, lens in self._lengths.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "InvertedIndex":
        ix = cls()
        for f, table in (data.get("fields") or {}).items():
            if f not in ix._postings:
                continue
            ix._postings[f] = {term: {int(d): list(pos) for d, pos in docs.items()} for term, docs in table.items()}
        for f, lens in (data.get("lengths") or {}).items():
            if f in ix._lengths:
                ix._lengths[f] = {int(d): int(n) for d, n in lens.items()}
        return ix
