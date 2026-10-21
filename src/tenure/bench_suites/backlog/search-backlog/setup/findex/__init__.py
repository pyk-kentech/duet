"""findex: 표준 라이브러리만 쓰는 작은 전문 검색 라이브러리와 CLI.

    >>> from findex import Index
    >>> idx = Index()
    >>> doc = idx.add("Hello world", body="The quick brown fox")
    >>> idx.search("fox").ids()
    [1]

공개 이름은 이 모듈에서 import 한다. 그 밖의 모듈 구조는 바뀔 수 있다.
"""

from findex.analyzer import DEFAULT_STOPWORDS, Analyzer
from findex.document import Document
from findex.engine import Index
from findex.errors import DocumentNotFound, FindexError, QuerySyntaxError, StorageError
from findex.search import Hit, SearchResults

__version__ = "0.4.2"

__all__ = [
    "Analyzer",
    "DEFAULT_STOPWORDS",
    "Document",
    "DocumentNotFound",
    "FindexError",
    "Hit",
    "Index",
    "QuerySyntaxError",
    "SearchResults",
    "StorageError",
    "__version__",
]
