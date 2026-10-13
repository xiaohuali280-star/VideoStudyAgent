class StudyError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        retryable: bool = False,
        step: str | None = None,
    ):
        super().__init__(code)
        self.code, self.message, self.status = code, message, status
        self.retryable, self.step = retryable, step
