"""태그 facet (태그별 문서 수).

규칙 (README 의 "facets" 절):

* :func:`findex.textutil.tag_key` 가 같은 태그(대소문자·악센트만 다른 태그)는 같은 태그로
  센다(``Python`` = ``python``, ``Café`` = ``cafe``).
* 한 문서는 같은 태그를 한 번만 센다.
* 이름(label)은 그 태그를 가진 문서 중 **id 가 가장 작은(먼저 넣은) 문서의 철자**다.
  그 문서를 지우면 다음 문서의 철자가 된다. 태그 철자는 바꾸지 않는다.
* 정렬은 개수 내림차순, 같으면 이름의 정규형(``tag_key``) 사전순.
* ``limit`` 을 주면 앞에서부터 그만큼만.
"""

from __future__ import annotations

from typing import Iterable

from findex.document import Document
from findex.textutil import tag_key


def tag_facets(docs: Iterable[Document], limit: int | None = None) -> list[tuple[str, int]]:
    """``docs`` 의 태그별 문서 수: ``[(이름, 개수), ...]``."""
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
        raise ValueError(f"limit 은 1 이상의 정수여야 합니다: {limit!r}")
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    for doc in sorted(docs, key=lambda d: d.id):
        seen: set[str] = set()
        for tag in doc.tags:
            key = tag_key(tag)
            if key in seen:
                continue
            seen.add(key)
            counts[key] = counts.get(key, 0) + 1
            labels.setdefault(key, tag)
    items = sorted(counts, key=lambda k: (-counts[k], k))
    if limit is not None:
        items = items[:limit]
    return [(labels[k], counts[k]) for k in items]


def format_facets(facets: list[tuple[str, int]]) -> str:
    """CLI 출력: 한 줄에 ``이름<TAB>개수``."""
    return "\n".join(f"{label}\t{count}" for label, count in facets)
