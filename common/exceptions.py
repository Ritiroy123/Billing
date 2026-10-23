from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class DomainError(Exception):
    """A business-rule error (not a bug). Turned into an HTTP error by api_exception_handler."""
    code = "domain_error"
    status_code = 400

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class InsufficientBalance(DomainError):
    code = "insufficient_balance"


class InvalidAmount(DomainError):
    code = "invalid_amount"


class NotFound(DomainError):
    code = "not_found"
    status_code = 404


def api_exception_handler(exc, context):
    if isinstance(exc, DomainError):
        return Response({"error": exc.code, "detail": exc.message}, status=exc.status_code)
    return drf_exception_handler(exc, context)   # everything else: DRF's normal handling



class InvalidTransition(DomainError):
    code = "invalid_transition"


class NotAllowed(DomainError):
    code = "not_allowed"
    status_code = 403


class ActiveSessionExists(DomainError):
    code = "active_session_exists"

