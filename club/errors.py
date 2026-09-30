class DomainError(Exception):
    def __init__(self, status: int, code: str, message: str, extra: dict | None = None):
        self.status, self.code, self.message, self.extra = status, code, message, extra or {}


def fail(status, code, message, **extra):
    raise DomainError(status, code, message, extra)
