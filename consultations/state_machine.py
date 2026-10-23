from common.exceptions import InvalidTransition
from .models import ConsultationSession

S = ConsultationSession.Status

# action  →  (statuses it is allowed FROM, status it moves TO)
TRANSITIONS = {
    "assign": ({S.UNASSIGNED}, S.ASSIGNED),
    "accept": ({S.ASSIGNED}, S.ACCEPTED),
    "start":  ({S.ACCEPTED}, S.IN_PROGRESS),
    "end":    ({S.IN_PROGRESS}, S.COMPLETED),
    "cancel": ({S.UNASSIGNED, S.ASSIGNED, S.ACCEPTED}, S.CANCELLED),
}


def apply_transition(session, action):
    """Move the session to the next status, or raise InvalidTransition (→ HTTP 400)."""
    allowed_from, target = TRANSITIONS[action]
    if session.status not in allowed_from:
        allowed = ", ".join(sorted(allowed_from))
        raise InvalidTransition(
            f"Cannot '{action}' a session that is '{session.status}'. "
            f"Allowed only when status is: {allowed}."
        )
    session.status = target
