"""문서 모델과 입력 검증.

문서는 ``id``, ``title``, ``body``, ``tags``, ``date`` 다섯 필드를 가진다.

* ``title``: 앞뒤 공백을 뗀 뒤 비어 있으면 안 된다. **저장은 원문 그대로**(공백도 떼지 않는다).
* ``body``: 문자열, 원문 그대로.
* ``tags``: 문자열 목록. 각 태그의 앞뒤 공백을 떼고, 빈 태그는 버리고, 같은 태그
  (대소문자 무시)가 여러 번 있으면 처음 것만 남긴다. 나머지는 쓴 철자 그대로 둔다.
* ``date``: ``YYYY-MM-DD`` 문자열 또는 ``None``. **문서의 날짜는 완전한 날짜만** 받는다
  (``2024-03`` 같은 부분 날짜는 검색어의 날짜 범위에서만 쓸 수 있다).

문서는 바꿀 수 없는(frozen) 값이다. 바꿀 때는 :meth:`Index.update` 가 새 값을 만든다.

여러 문서 한꺼번에 넣기·내보내기 (JSON Lines) 도 여기 있다.

* :func:`validate_items` — ``Index.add_many`` 가 넣기 전에 모든 항목을 먼저 검사한다
  (전부 아니면 전무).
* :func:`read_jsonl` / :func:`write_jsonl` — CLI 의 ``import`` / ``export`` 가 쓰는 파일 형식.
  한 줄에 문서 하나: ``{"title": ..., "body": ..., "tags": [...], "date": ...}``.
  ``export`` 는 ``id`` 도 쓰지만 ``import`` 는 ``id`` 를 무시한다(새 id 를 붙인다).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date as _date
from pathlib import Path
from typing import Iterable

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class Document:
    id: int
    title: str
    body: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    date: str | None = None

    def date_value(self) -> _date | None:
        """``date`` 를 :class:`datetime.date` 로 (없으면 ``None``)."""
        return _date.fromisoformat(self.date) if self.date else None

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "body": self.body, "tags": list(self.tags), "date": self.date}

    @classmethod
    def from_dict(cls, data: dict) -> "Document":
        return make_document(int(data["id"]), data.get("title", ""), data.get("body", ""),
                             data.get("tags") or (), data.get("date"))


def check_title(title: object) -> str:
    if not isinstance(title, str):
        raise ValueError("제목은 문자열이어야 합니다")
    if not title.strip():
        raise ValueError("제목이 비어 있습니다")
    return title


def check_body(body: object) -> str:
    if body is None:
        return ""
    if not isinstance(body, str):
        raise ValueError("본문은 문자열이어야 합니다")
    return body


def clean_tags(tags: Iterable[str] | None) -> tuple[str, ...]:
    """태그 정리: 앞뒤 공백 제거, 빈 태그 버림, 대소문자만 다른 중복은 처음 것만."""
    if tags is None:
        return ()
    if isinstance(tags, str):
        raise ValueError("tags 는 문자열 목록이어야 합니다")
    out: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        if not isinstance(tag, str):
            raise ValueError("태그는 문자열이어야 합니다")
        tag = tag.strip()
        if not tag:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return tuple(out)


def check_date(value: object) -> str | None:
    """문서 날짜 검증. 완전한 ``YYYY-MM-DD`` 만 받는다."""
    if value is None:
        return None
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ValueError(f"날짜는 YYYY-MM-DD 형식이어야 합니다: {value!r}")
    try:
        _date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"없는 날짜입니다: {value}") from None
    return value


def make_document(doc_id: int, title: object, body: object = "", tags: Iterable[str] | None = (),
                  date: object = None) -> Document:
    """검증을 거친 :class:`Document`."""
    return Document(id=doc_id, title=check_title(title), body=check_body(body),
                    tags=clean_tags(tags), date=check_date(date))


# ====================================================================== bulk (JSON Lines)
ALLOWED_KEYS = frozenset({"id", "title", "body", "tags", "date"})


class BulkError(ValueError):
    """``n`` 번째 항목(또는 줄, 1 부터)이 잘못되었다."""

    def __init__(self, n: int, message: str, unit: str = "항목"):
        super().__init__(f"{n}번째 {unit}: {message}")
        self.n = n


def validate_items(items: Iterable[dict]) -> list[dict]:
    """모든 항목을 검사하고 ``Index.add`` 의 키워드 인자 목록으로 바꾼다."""
    out: list[dict] = []
    for n, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise BulkError(n, "객체(dict)가 아닙니다")
        unknown = set(item) - ALLOWED_KEYS
        if unknown:
            raise BulkError(n, f"알 수 없는 키: {', '.join(sorted(unknown))}")
        try:
            fields = {
                "title": check_title(item.get("title")),
                "body": check_body(item.get("body", "")),
                "tags": list(clean_tags(item.get("tags") or ())),
                "date": check_date(item.get("date")),
            }
        except ValueError as e:
            raise BulkError(n, str(e)) from None
        out.append(fields)
    return out


def read_jsonl(path: str | Path) -> list[dict]:
    """JSON Lines 파일 -> dict 목록. 빈 줄은 건너뛴다. 틀린 줄은 ``BulkError`` (줄 번호)."""
    text = Path(path).read_text(encoding="utf-8")
    items: list[dict] = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as e:
            raise BulkError(n, f"JSON 이 아닙니다 ({e.msg})", unit="줄") from None
        if not isinstance(item, dict):
            raise BulkError(n, "객체가 아닙니다", unit="줄")
        items.append(item)
    return items


def write_jsonl(docs: Iterable[Document], path: str | Path) -> int:
    """문서들을 JSON Lines 로 쓴다. 쓴 문서 수를 돌려준다."""
    lines = [json.dumps(d.to_dict(), ensure_ascii=False) for d in docs]
    Path(path).write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return len(lines)
