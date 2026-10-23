from django.db import transaction
from django.utils import timezone
from accounts.models import User
from common.exceptions import NotAllowed, NotFound
from .models import ConsultationSession
from .state_machine import apply_transition
from django.db import IntegrityError, transaction
from django.utils import timezone
from accounts.models import User
from common.exceptions import ActiveSessionExists, InsufficientBalance, NotAllowed, NotFound
from wallet.models import Wallet
from .models import ConsultationSession
from .state_machine import apply_transition
from common.exceptions import ActiveSessionExists, InsufficientBalance, NotAllowed, NotFound   # (already there)
from wallet import services as wallet_services
from .models import BillingRecord, ConsultationSession


S = ConsultationSession.Status
MIN_BALANCE_MINUTES = 5



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



@transaction.atomic
def start(session_id, actor):
    session = _get_locked(session_id)
    if session.user_id != actor.id:
        raise NotAllowed("Only the session owner can start the session.")

    apply_transition(session, "start")                       # must be accepted_by_provider

    if ConsultationSession.objects.filter(user=session.user, status=S.IN_PROGRESS).exists():
        raise ActiveSessionExists("You already have a session in progress. End it first.")

    rate = session.provider.per_minute_rate
    required = rate * MIN_BALANCE_MINUTES
    balance = Wallet.objects.get(user=session.user).balance
    if balance < required:
        raise InsufficientBalance(
            f"Starting needs at least ₹{required} ({MIN_BALANCE_MINUTES} × ₹{rate}/min). "
            f"Your balance is ₹{balance}."
        )

    session.per_minute_rate = rate                           # 🔒 rate fixed from now on
    session.started_at = timezone.now()
    try:
        with transaction.atomic():                           # savepoint (explained below)
            session.save(update_fields=["status", "per_minute_rate", "started_at", "updated_at"])
    except IntegrityError:
        # The DB's one-active-session rule caught a race the check above missed
        raise ActiveSessionExists("You already have a session in progress. End it first.")
    return session

# ---------------- Billing ----------------

def _bill_elapsed_minutes(session, now):
    """Charge every fully elapsed minute that hasn't been charged yet. Caller must hold the session lock."""
    elapsed = int((now - session.started_at).total_seconds() // 60)

    for minute in range(session.billed_minutes + 1, elapsed + 1):
        try:
            wallet_services.debit(
                session.user, session.per_minute_rate,
                reason="session_billing", reference=f"session-{session.pk}-minute-{minute}",
            )
        except InsufficientBalance:
            break          # Step 10: end the session automatically here

        BillingRecord.objects.create(session=session, minute_number=minute, amount=session.per_minute_rate)
        session.billed_minutes = minute
        session.billed_amount += session.per_minute_rate

    session.save(update_fields=["billed_minutes", "billed_amount", "updated_at"])


@transaction.atomic
def bill_session(session_id, now=None):
    """Safe to call any number of times: only not-yet-charged full minutes are billed."""
    session = _get_locked(session_id)
    if session.status != S.IN_PROGRESS:
        return session                       # nothing to bill → harmless no-op
    _bill_elapsed_minutes(session, now or timezone.now())
    return session


def _finish(session, ended_by, end_reason, now):
    """Close an in-progress session. Reused by user/provider end now and system end in Step 10."""
    apply_transition(session, "end")
    session.ended_at = now
    session.ended_by = ended_by
    session.end_reason = end_reason
    session.save(update_fields=["status", "ended_at", "ended_by", "end_reason", "updated_at"])


@transaction.atomic
def end(session_id, actor):
    session = _get_locked(session_id)
    if actor.id == session.user_id:
        ended_by, reason = ConsultationSession.EndedBy.USER, ConsultationSession.EndReason.USER_ENDED
    elif actor.id == session.provider_id:
        ended_by, reason = ConsultationSession.EndedBy.PROVIDER, ConsultationSession.EndReason.PROVIDER_ENDED
    else:
        raise NotAllowed("Only participants can end this session.")

    now = timezone.now()
    if session.status == S.IN_PROGRESS:
        _bill_elapsed_minutes(session, now)      # charge full minutes up to the end time
    _finish(session, ended_by, reason, now)      # raises InvalidTransition if not in progress
    return session
