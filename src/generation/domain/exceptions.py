class DomainError(Exception):
    """Base class for expected business failures."""


class UnknownUserError(DomainError):
    pass


class UnknownModelError(DomainError):
    pass


class NoSuitableLegError(DomainError):
    pass


class InsufficientTokensError(DomainError):
    pass


class ActiveTaskLimitError(DomainError):
    pass


class InvalidSignatureError(DomainError):
    pass
