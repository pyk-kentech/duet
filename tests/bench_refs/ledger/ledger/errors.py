class LedgerError(ValueError):
    def __init__(self, message, lineno=None):
        super().__init__(f"{lineno}번째 줄: {message}" if lineno else message)
        self.lineno = lineno
