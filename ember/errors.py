class CompileError(Exception):
    """A problem in the C source, reported with its line number."""

    def __init__(self, message: str, line: int = 0) -> None:
        super().__init__(f"line {line}: {message}" if line else message)
        self.line = line
