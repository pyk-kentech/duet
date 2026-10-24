"""분석기: 원문 -> (색인어, 위치) 목록.

순서: 토큰 자르기(:mod:`findex.tokenizer`) -> 표준형(:func:`findex.textutil.normalize`)
-> 불용어 빼기 -> 어간 추출(:mod:`findex.stemmer`, 켜져 있을 때).

**위치 규칙 (README 에 적힌 동작)**: 불용어는 위치를 차지하지 않는다. 불용어를 뺀 뒤 남은
단어에 0, 1, 2, ... 를 차례로 붙인다. 그래서 구절 검색은 불용어 자리를 무시한다:
``"lord of the rings"`` 는 ``lord rings`` 로 분석되고, 원문 ``Lord of the Rings`` 와
``lord rings`` 와 ``lord of rings`` 모두에 맞는다.

**하이픈 단어** (``e-mail``): 조각(``e``, ``mail``)은 위의 규칙대로 위치를 차지하고,
합친 형태(``email``)는 첫 조각과 같은 위치에 덧붙인다(``alias``). 조각과 합친 형태 모두
정규화·불용어·어간을 똑같이 거친다. 필드 길이(BM25)는 조각만 센다.

검색어 쪽:

* :meth:`Analyzer.query_terms` — 따옴표 밖 단어. 하이픈 단어는 합친 형태 하나로.
* :meth:`Analyzer.phrase_terms` — 구절. 하이픈 단어는 조각들로.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from findex.stemmer import stem as _stem
from findex.textutil import normalize
from findex.tokenizer import iter_words

#: 기본 영어 불용어. ``Index(stopwords=...)`` 로 바꿀 수 있다.
DEFAULT_STOPWORDS: frozenset[str] = frozenset("""
a an and are as at be but by for from has have he in is it its of on or not
she that the their there they this to was were will with
""".split())


@dataclass(frozen=True)
class Term:
    """분석 결과 하나: 색인어와 그 위치. ``alias`` 는 하이픈 단어의 합친 형태(길이에 안 셈)."""

    term: str
    position: int
    alias: bool = False


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
        for word in iter_words(text):
            if not word.hyphenated:
                term = self.normalize_token(word.parts[0].text)
                if term is not None:
                    out.append(Term(term, pos))
                    pos += 1
                continue
            joined = self.normalize_token(word.joined)
            fragments = [t for t in (self.normalize_token(p.text) for p in word.parts) if t is not None]
            if joined is not None:
                out.append(Term(joined, pos, alias=bool(fragments)))
            for frag in fragments:
                out.append(Term(frag, pos))
                pos += 1
            if joined is not None and not fragments:
                pos += 1
        return out

    def query_terms(self, text: str) -> list[str]:
        """따옴표 밖 검색어 단어 -> 색인어 목록 (하이픈 단어는 합친 형태 하나)."""
        out: list[str] = []
        for word in iter_words(text):
            source = word.joined if word.hyphenated else word.parts[0].text
            term = self.normalize_token(source)
            if term is not None:
                out.append(term)
        return out

    def phrase_terms(self, text: str) -> list[str]:
        """구절 -> 색인어 목록 (하이픈 단어는 조각들)."""
        return [t.term for t in self.analyze(text) if not t.alias]

    def single_term(self, word: str) -> str | None:
        """단어 하나가 색인어 하나가 되면 그 색인어, 아니면 ``None`` (동의어 등록에 쓴다)."""
        terms = self.query_terms(word)
        return terms[0] if len(terms) == 1 else None

    def length(self, text: str) -> int:
        """BM25 에 쓰는 필드 길이 = 분석 후 색인어 수 (하이픈 단어의 합친 형태는 세지 않는다)."""
        return sum(1 for t in self.analyze(text) if not t.alias)

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
