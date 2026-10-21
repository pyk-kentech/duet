"""분석기: 원문 -> (색인어, 위치) 목록.

순서: 토큰 자르기(:mod:`findex.tokenizer`) -> 표준형(:func:`findex.textutil.normalize`)
-> 불용어 빼기 -> 어간 추출(:mod:`findex.stemmer`, 켜져 있을 때).

**위치 규칙 (README 에 적힌 동작)**: 불용어는 위치를 차지하지 않는다. 불용어를 뺀 뒤 남은
단어에 0, 1, 2, ... 를 차례로 붙인다. 그래서 구절 검색은 불용어 자리를 무시한다:
``"lord of the rings"`` 는 ``lord rings`` 로 분석되고, 원문 ``Lord of the Rings`` 와
``lord rings`` 와 ``lord of rings`` 모두에 맞는다.

같은 분석기를 색인과 검색어 양쪽에 쓴다(:meth:`Analyzer.query_terms`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from findex.stemmer import stem as _stem
from findex.textutil import normalize
from findex.tokenizer import iter_tokens

#: 기본 영어 불용어. ``Index(stopwords=...)`` 로 바꿀 수 있다.
DEFAULT_STOPWORDS: frozenset[str] = frozenset("""
a an and are as at be but by for from has have he in is it its of on or not
she that the their there they this to was were will with
""".split())


@dataclass(frozen=True)
class Term:
    """분석 결과 하나: 색인어와 그 위치."""

    term: str
    position: int


class Analyzer:
    """토크나이저 + 정규화 + 불용어 + 어간.

    ``stopwords``: ``None`` 이면 :data:`DEFAULT_STOPWORDS`, 아니면 그 단어들로 **바꾼다**
    (빈 목록이면 불용어 없음). 불용어도 :func:`normalize` 로 비교한다.
    ``stem``: 어간 추출을 할지.
    """

    def __init__(self, stopwords: Iterable[str] | None = None, stem: bool = True):
        if stopwords is None:
            self.custom_stopwords: list[str] | None = None
            words = DEFAULT_STOPWORDS
        else:
            if isinstance(stopwords, str):
                raise ValueError("stopwords 는 단어 목록이어야 합니다")
            self.custom_stopwords = list(stopwords)
            words = self.custom_stopwords
        self.stopwords = frozenset(normalize(w).strip() for w in words if w.strip())
        self.stem = bool(stem)

    # ------------------------------------------------------------------ core
    def normalize_token(self, text: str) -> str | None:
        """토큰 하나 -> 색인어. 불용어면 ``None``."""
        term = normalize(text)
        if not term or term in self.stopwords:
            return None
        if self.stem:
            term = _stem(term)
        return term

    def analyze(self, text: str) -> list[Term]:
        """원문 전체를 분석한다. 위치는 불용어를 뺀 순번."""
        out: list[Term] = []
        pos = 0
        for tok in iter_tokens(text):
            term = self.normalize_token(tok.text)
            if term is None:
                continue
            out.append(Term(term, pos))
            pos += 1
        return out

    def query_terms(self, text: str) -> list[str]:
        """검색어 조각(단어 하나 또는 구절)을 색인어 목록으로."""
        return [t.term for t in self.analyze(text)]

    def length(self, text: str) -> int:
        """BM25 에 쓰는 필드 길이 = 분석 후 색인어 수."""
        return len(self.analyze(text))

    # ------------------------------------------------------------------ settings
    def settings(self) -> dict:
        """저장 형식의 ``settings`` 에 들어가는 값."""
        return {"stopwords": self.custom_stopwords, "stem": self.stem}

    @classmethod
    def from_settings(cls, data: dict) -> "Analyzer":
        return cls(stopwords=data.get("stopwords"), stem=data.get("stem", True))

    def __repr__(self) -> str:
        sw = "default" if self.custom_stopwords is None else len(self.stopwords)
        return f"Analyzer(stopwords={sw}, stem={self.stem})"
