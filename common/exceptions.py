class DomainError(Exception):
    """A business-rule error (not a bug). Later mapped to HTTP 400."""
    code = "domain_error"

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class InsufficientBalance(DomainError):
    code = "insufficient_balance"


class InvalidAmount(DomainError):
    code = "invalid_amount"
