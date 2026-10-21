"""findex 의 오류 계층.

모든 오류는 :class:`FindexError` 의 하위 클래스다. CLI 는 이 오류(와 ``ValueError``)를
잡아 ``오류: <메시지>`` 로 보여 준다. 입력값 검증 실패(빈 제목, 잘못된 날짜 형식 등)는
관례대로 ``ValueError`` 를 쓴다.
"""

from __future__ import annotations


class FindexError(Exception):
    """findex 가 일부러 내는 모든 오류의 부모."""


class DocumentNotFound(FindexError):
    """없는 문서(또는 이미 지운 문서)의 id 를 썼다."""

    def __init__(self, doc_id: object):
        super().__init__(f"문서를 찾을 수 없습니다: {doc_id}")
        self.doc_id = doc_id


class QuerySyntaxError(FindexError):
    """검색어 문법 오류 (닫히지 않은 따옴표·괄호, 잘못된 날짜 범위 등)."""


class StorageError(FindexError):
    """색인 파일을 읽거나 쓸 수 없다 (깨진 JSON, 지원하지 않는 형식 등)."""
