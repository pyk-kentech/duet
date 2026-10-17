class IssueError(Exception):
    """issuetrack 오류의 공통 부모."""


class NotFound(IssueError):
    pass


class InvalidTransition(IssueError):
    pass


class QueryError(IssueError):
    pass


class StorageError(IssueError):
    pass


class CsvFormatError(IssueError):
    pass
