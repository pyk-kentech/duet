"""색인 파일 저장·읽기 (JSON).

지금 형식은 **버전 2** 다 (README 의 "저장 형식" 절)::

    {
      "format": "findex",
      "version": 2,
      "settings": {"stopwords": null | [...], "stem": true, "boosts": {"title": 2.0, "body": 1.0}},
      "documents": [{"id": 1, "title": "...", "body": "...", "tags": [...], "date": "2024-01-31" | null}, ...],
      "index": {"next_id": 4, "fields": {...역색인...}, "lengths": {...}}
    }

* ``documents`` 에는 지우지 않은 문서만 id 순으로 들어간다.
* ``index.next_id`` 는 다음에 붙일 id 다(지운 id 를 다시 쓰지 않기 위해 저장한다).
* 읽을 때 ``index`` 의 역색인을 그대로 쓴다(다시 분석하지 않는다).

옛 **버전 1** 파일도 읽는다(쓰지는 않는다)::

    {"version": 1, "next_id": 3, "docs": {"1": {"title": "...", "text": "본문", "tags": "a,b", "date": "2024-01-31"}}}

버전 1 에는 설정이 없어서 기본 설정으로 읽고, 역색인이 없어서 문서로 다시 만든다.
태그는 쉼표로 이은 문자열이다.

쓰기는 같은 폴더의 임시 파일에 쓴 뒤 ``os.replace`` 로 바꿔 넣는다(쓰다 죽어도 옛 파일이 남는다).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from findex.document import Document, make_document
from findex.errors import StorageError
from findex.index import InvertedIndex

FORMAT = "findex"
VERSION = 2


# ====================================================================== write
def dump(index) -> dict:
    """``Index`` -> 저장할 dict (버전 2)."""
    settings = index.analyzer.settings()
    settings["boosts"] = dict(index.boosts)
    ix = index._index.to_dict()
    ix["next_id"] = index.next_id
    return {
        "format": FORMAT,
        "version": VERSION,
        "settings": settings,
        "documents": [d.to_dict() for d in index.documents()],
        "index": ix,
    }


def save(index, path: str | Path) -> None:
    path = Path(path)
    data = dump(index)
    text = json.dumps(data, ensure_ascii=False, indent=1)
    folder = path.parent if str(path.parent) else Path(".")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".findex-", suffix=".tmp", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as e:
        raise StorageError(f"색인 파일을 쓸 수 없습니다: {path} ({e})") from None


# ====================================================================== read
def load(path: str | Path):
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise StorageError(f"색인 파일이 없습니다: {path}") from None
    except OSError as e:
        raise StorageError(f"색인 파일을 읽을 수 없습니다: {path} ({e})") from None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise StorageError(f"색인 파일이 깨졌습니다: {path} ({e})") from None
    return restore(data)


def restore(data: object):
    """저장된 dict -> ``Index``."""
    if not isinstance(data, dict):
        raise StorageError("색인 파일의 최상위는 객체여야 합니다")
    version = data.get("version")
    if version == 1:
        return _from_v1(data)
    if isinstance(version, int) and not isinstance(version, bool) and version >= 2:
        # newer writers only add fields, so anything from v2 on is read as v2
        if data.get("format") != FORMAT:
            raise StorageError("findex 색인 파일이 아닙니다")
        return _from_v2(data)
    raise StorageError(f"지원하지 않는 형식 버전입니다: {version!r}")


def _new_index(settings: dict):
    from findex.engine import Index
    try:
        return Index(stopwords=settings.get("stopwords"), stem=settings.get("stem", True),
                     boosts=settings.get("boosts"))
    except (TypeError, ValueError) as e:
        raise StorageError(f"설정이 잘못되었습니다: {e}") from None


def _documents(items: list) -> list[Document]:
    try:
        docs = [Document.from_dict(d) for d in items]
    except (KeyError, TypeError, ValueError) as e:
        raise StorageError(f"문서가 잘못되었습니다: {e}") from None
    ids = [d.id for d in docs]
    if len(set(ids)) != len(ids):
        raise StorageError("같은 id 의 문서가 둘 이상입니다")
    return sorted(docs, key=lambda d: d.id)


def _from_v2(data: dict):
    index = _new_index(data.get("settings") or {})
    docs = _documents(data.get("documents") or [])
    ix = data.get("index") or {}
    try:
        inverted = InvertedIndex.from_dict(ix)
    except (AttributeError, TypeError, ValueError) as e:
        raise StorageError(f"역색인이 잘못되었습니다: {e}") from None
    index._restore(docs, inverted, ix.get("next_id"))
    return index


def _split_tags(value: object) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return str(value).split(",")


def _from_v1(data: dict):
    index = _new_index({})
    raw = data.get("docs") or {}
    if not isinstance(raw, dict):
        raise StorageError("버전 1 파일의 docs 는 객체여야 합니다")
    docs: list[Document] = []
    try:
        for key in sorted(raw, key=int):
            item = raw[key]
            docs.append(make_document(int(key), item.get("title", ""), item.get("text", ""),
                                      _split_tags(item.get("tags")), item.get("date")))
    except (TypeError, ValueError, AttributeError) as e:
        raise StorageError(f"버전 1 문서가 잘못되었습니다: {e}") from None
    index._restore(docs, None, data.get("next_id"))
    return index
