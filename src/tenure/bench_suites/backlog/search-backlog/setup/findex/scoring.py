"""BM25 점수.

필드마다 따로 BM25 를 구하고 필드 가중치(boost)를 곱해 더한다.

* ``idf(t) = ln(1 + (N - df + 0.5) / (df + 0.5))`` — ``N`` 은 (지우지 않은) 문서 수,
  ``df`` 는 그 필드에 ``t`` 가 있는 문서 수.
* ``bm25 = idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len / avglen))``,
  ``k1 = 1.2``, ``b = 0.75``. ``len`` 은 그 문서의 필드 길이(분석 후 색인어 수),
  ``avglen`` 은 지우지 않은 문서들의 평균 필드 길이(0 이면 1 로 본다).
* 기본 가중치: ``title`` 2.0, ``body`` 1.0.

API 의 점수는 반올림하지 않는다. CLI 출력만 소수 넷째 자리로 반올림한다.
"""

from __future__ import annotations

import math
from typing import Iterable

from findex.index import TEXT_FIELDS, InvertedIndex

K1 = 1.2
B = 0.75
DEFAULT_BOOSTS: dict[str, float] = {"title": 2.0, "body": 1.0}


def check_boosts(boosts: dict | None) -> dict[str, float]:
    """``Index(boosts=...)`` 검증: 텍스트 필드만, 양수만. 빠진 필드는 기본값."""
    out = dict(DEFAULT_BOOSTS)
    for field, value in (boosts or {}).items():
        if field not in TEXT_FIELDS:
            raise ValueError(f"가중치를 줄 수 없는 필드입니다: {field}")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"가중치는 양수여야 합니다: {field}={value!r}")
        out[field] = float(value)
    return out


def idf(n_docs: int, df: int) -> float:
    return math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))


def bm25(tf: int, length: int, avg_length: float, idf_value: float, k1: float = K1, b: float = B) -> float:
    if tf <= 0:
        return 0.0
    norm = 1.0 - b + b * (length / avg_length)
    return idf_value * tf * (k1 + 1.0) / (tf + k1 * norm)


class CorpusStats:
    """문서 수와 필드별 길이 합. 평균 필드 길이를 구하는 데 쓴다."""

    def __init__(self) -> None:
        self.doc_count = 0
        self.total_length: dict[str, int] = {f: 0 for f in TEXT_FIELDS}

    def refresh(self, index: InvertedIndex, live_ids: Iterable[int]) -> None:
        """지우지 않은 문서들로 통계를 다시 센다."""
        ids = list(live_ids)
        self.doc_count = len(ids)
        for f in TEXT_FIELDS:
            lengths = index.lengths(f)
            self.total_length[f] = sum(lengths.get(d, 0) for d in ids)

    def avg_length(self, field: str) -> float:
        if self.doc_count == 0:
            return 1.0
        avg = self.total_length[field] / self.doc_count
        return avg if avg > 0 else 1.0

    def __repr__(self) -> str:
        return f"CorpusStats(docs={self.doc_count}, lengths={self.total_length})"
