"""동의어 묶음.

* 묶음은 단어 2개 이상. 각 단어는 색인과 같은 분석을 거쳐 색인어 **하나**가 되어야 한다
  (하이픈 단어는 합친 형태). 아니면 ``ValueError`` 이고 아무것도 바꾸지 않는다.
* 묶음은 양방향이다. 새 묶음이 기존 묶음과 색인어를 공유하면 하나로 합친다: 합친 묶음은
  가장 앞 묶음 자리에, 단어는 기존 묶음들의 단어(묶음 순서대로) 다음에 새 단어. 색인어가 같은
  단어는 처음 것만 남긴다.
* 검색할 때 적용한다(문서를 다시 색인하지 않는다): :meth:`SynonymTable.expand`.
"""

from __future__ import annotations

from typing import Iterable

from findex.analyzer import Analyzer


class SynonymTable:
    def __init__(self) -> None:
        self._groups: list[list[tuple[str, str]]] = []      # [(original word, term), ...]
        self._by_term: dict[str, int] = {}

    def add(self, words: Iterable[str], analyzer: Analyzer) -> None:
        words = list(words)
        if len(words) < 2:
            raise ValueError("동의어는 단어 2개 이상이어야 합니다")
        pairs: list[tuple[str, str]] = []
        for w in words:
            if not isinstance(w, str):
                raise ValueError(f"동의어는 문자열이어야 합니다: {w!r}")
            term = analyzer.single_term(w)
            if term is None:
                raise ValueError(f"동의어는 색인어 하나가 되는 단어여야 합니다: {w!r}")
            pairs.append((w, term))
        if len({t for _, t in pairs}) < 2:
            raise ValueError("동의어는 색인어가 서로 다른 단어 2개 이상이어야 합니다")
        hit = sorted({self._by_term[t] for _, t in pairs if t in self._by_term})
        merged: list[tuple[str, str]] = []
        for gi in hit:
            merged.extend(self._groups[gi])
        merged.extend(pairs)
        seen: set[str] = set()
        group = []
        for w, t in merged:
            if t in seen:
                continue
            seen.add(t)
            group.append((w, t))
        if hit:
            self._groups[hit[0]] = group
            for gi in reversed(hit[1:]):
                del self._groups[gi]
        else:
            self._groups.append(group)
        self._reindex()

    def _reindex(self) -> None:
        self._by_term = {t: gi for gi, group in enumerate(self._groups) for _, t in group}

    def expand(self, term: str) -> tuple[str, ...]:
        """``term`` 과 같은 묶음의 색인어들(자기 자신 포함). 묶음이 없으면 ``(term,)``."""
        gi = self._by_term.get(term)
        if gi is None:
            return (term,)
        return tuple(t for _, t in self._groups[gi])

    def groups(self) -> list[list[str]]:
        """등록한 철자 그대로의 묶음 목록."""
        return [[w for w, _ in group] for group in self._groups]

    def __len__(self) -> int:
        return len(self._groups)
