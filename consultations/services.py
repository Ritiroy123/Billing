from django.db import transaction
from django.utils import timezone
from accounts.models import User
from common.exceptions import NotAllowed, NotFound
from .models import ConsultationSession
from .state_machine import apply_transition


def _get_locked(session_id):
    try:
        return ConsultationSession.objects.select_for_update().get(pk=session_id)
    except ConsultationSession.DoesNotExist:
        raise NotFound(f"Session {session_id} not found.")


def create_session(user):
    return ConsultationSession.objects.create(user=user)


@transaction.atomic
def assign(session_id, actor, provider_id):
    session = _get_locked(session_id)
    if session.user_id != actor.id:
        raise NotAllowed("Only the session owner can assign a provider.")
    provider = User.objects.filter(pk=provider_id, role=User.Role.PROVIDER).first()
    if provider is None:
        raise NotFound(f"Provider {provider_id} not found.")

    apply_transition(session, "assign")
    session.provider = provider
    session.save(update_fields=["status", "provider", "updated_at"])
    return session


@transaction.atomic
def accept(session_id, actor):
    session = _get_locked(session_id)
    if session.provider_id != actor.id:
        raise NotAllowed("Only the assigned provider can accept this session.")

    apply_transition(session, "accept")
    session.save(update_fields=["status", "updated_at"])
    return session


@transaction.atomic
def cancel(session_id, actor):
    session = _get_locked(session_id)
    if actor.id not in (session.user_id, session.provider_id):
        raise NotAllowed("Only participants can cancel this session.")

    apply_transition(session, "cancel")
    session.ended_at = timezone.now()
    session.ended_by = (ConsultationSession.EndedBy.USER if actor.id == session.user_id
                        else ConsultationSession.EndedBy.PROVIDER)
    session.end_reason = ConsultationSession.EndReason.CANCELLED
    session.save(update_fields=["status", "ended_at", "ended_by", "end_reason", "updated_at"])
    return session
