"""참조 구현: 숨은 테스트 검증용."""

from csvq.engine import query
from csvq.errors import QueryError

__all__ = ["QueryError", "query"]
