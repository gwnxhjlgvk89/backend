class DomainError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def fail(status, code, message):
    raise DomainError(status, code, message)
