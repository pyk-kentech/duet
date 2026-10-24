"""색인 파일 저장·읽기 (JSON).

지금 형식은 **버전 3** 다 (README 의 "저장 형식" 절)::

    {
      "format": "findex",
      "version": 3,
      "settings": {"stopwords": null | [...], "stem": true, "boosts": {"title": 2.0, "body": 1.0},
                   "synonyms": [["car", "automobile"], ...]},
      "next_id": 4,
      "documents": [{"id": 1, "title": "...", "body": "...", "tags": [...], "date": "2024-01-31" | null}, ...]
    }

* ``documents`` 에는 지우지 않은 문서만 id 순으로 들어간다.
* ``next_id`` 는 다음에 붙일 id 다(지운 id 를 다시 쓰지 않기 위해 저장한다).
* 역색인은 저장하지 않는다. 읽을 때 언제나 문서로부터 지금 분석 규칙으로 다시 만든다.

옛 형식도 읽는다(쓰지는 않는다).

* **버전 2**: 버전 3 과 같되 ``synonyms`` 가 없고, ``next_id`` 가 ``index.next_id`` 에 있고,
  ``index`` 에 옛 역색인이 들어 있다(읽을 때 무시하고 다시 만든다).
* **버전 1**: ``{"version": 1, "next_id": 3, "docs": {"1": {"title": "...", "text": "본문",
  "tags": "a,b", "date": "2024-01-31"}}}`` — 설정은 기본값, 태그는 쉼표로 이은 문자열.

그 밖의 ``version`` 은 ``StorageError`` 다(앞으로 나올 버전도 읽지 않는다).

쓰기는 같은 폴더의 임시 파일에 쓴 뒤 ``os.replace`` 로 바꿔 넣는다(쓰다 죽어도 옛 파일이 남는다).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from findex.document import Document, make_document
from findex.errors import StorageError

FORMAT = "findex"
VERSION = 3
READABLE = (1, 2, 3)


# ====================================================================== write
def dump(index) -> dict:
    """``Index`` -> 저장할 dict (버전 3)."""
    settings = index.analyzer.settings()
    settings["boosts"] = dict(index.boosts)
    settings["synonyms"] = index.synonyms()
    return {
        "format": FORMAT,
        "version": VERSION,
        "settings": settings,
        "next_id": index.next_id,
        "documents": [d.to_dict() for d in index.documents()],
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
    if isinstance(version, bool) or version not in READABLE:
        raise StorageError(f"지원하지 않는 형식 버전입니다: {version!r}")
    if version == 1:
        return _from_v1(data)
    if data.get("format") != FORMAT:
        raise StorageError("findex 색인 파일이 아닙니다")
    if version == 2:
        ix = data.get("index") or {}
        if not isinstance(ix, dict):
            raise StorageError("버전 2 파일의 index 는 객체여야 합니다")
        return _from_settings_and_docs(data, ix.get("next_id"))
    return _from_settings_and_docs(data, data.get("next_id"))


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


def _from_settings_and_docs(data: dict, next_id: object):
    settings = data.get("settings") or {}
    if not isinstance(settings, dict):
        raise StorageError("settings 는 객체여야 합니다")
    index = _new_index(settings)
    try:
        for group in settings.get("synonyms") or []:
            index.add_synonyms(*group)
    except (TypeError, ValueError) as e:
        raise StorageError(f"동의어가 잘못되었습니다: {e}") from None
    docs = _documents(data.get("documents") or [])
    try:
        index._restore(docs, int(next_id or 0))
    except (TypeError, ValueError) as e:
        raise StorageError(f"next_id 가 잘못되었습니다: {e}") from None
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
    index._restore(docs, data.get("next_id"))
    return index
