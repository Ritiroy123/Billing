from django.test import SimpleTestCase
from rest_framework.test import APITestCase
from accounts.models import User
from common.exceptions import InvalidTransition
from .models import ConsultationSession
from .state_machine import apply_transition, TRANSITIONS
from decimal import Decimal
from wallet import services as wallet_services


class StartEndTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("riya", password="x")
        self.provider = User.objects.create_user(
            "doc", password="x", role=User.Role.PROVIDER, per_minute_rate=Decimal("50"))

    # helpers
    def as_(self, who):
        self.client.force_authenticate(who)

    def fund(self, amount):
        wallet_services.credit(self.user, Decimal(amount), reason="test")

    def accepted_session(self, provider=None):
        provider = provider or self.provider
        s = ConsultationSession.objects.create(user=self.user, provider=provider, status=S.ACCEPTED)
        return s.pk

    def start(self, sid):
        self.as_(self.user)
        return self.client.post(f"/api/sessions/{sid}/start/")

    def end(self, sid, who):
        self.as_(who)
        return self.client.post(f"/api/sessions/{sid}/end/")

    def balance(self):
        self.user.wallet.refresh_from_db()
        return self.user.wallet.balance

    # REQUIRED TEST #1
    def test_cannot_start_with_less_than_5_minutes_balance(self):
        self.fund("249")                                   # needs 5 × 50 = 250
        sid = self.accepted_session()
        r = self.start(sid)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["error"], "insufficient_balance")
        session = ConsultationSession.objects.get(pk=sid)
        self.assertEqual(session.status, S.ACCEPTED)       # did not start
        self.assertIsNone(session.started_at)
        self.assertEqual(self.balance(), Decimal("249.00"))  # nothing charged

    def test_can_start_with_exactly_5_minutes_balance(self):
        self.fund("250")
        r = self.start(self.accepted_session())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], S.IN_PROGRESS)
        self.assertEqual(r.data["per_minute_rate"], "50.00")
        self.assertIsNotNone(r.data["started_at"])
        self.assertEqual(self.balance(), Decimal("250.00"))  # start only checks, no charge

    # REQUIRED TEST #4
    def test_end_before_start_returns_400(self):
        sid = self.accepted_session()
        r = self.end(sid, self.user)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["error"], "invalid_transition")

    def test_cannot_start_twice(self):
        self.fund("500")
        sid = self.accepted_session()
        self.start(sid)
        self.assertEqual(self.start(sid).status_code, 400)

    def test_cannot_have_two_sessions_in_progress(self):
        self.fund("1000")
        doc2 = User.objects.create_user("doc2", password="x", role=User.Role.PROVIDER,
                                        per_minute_rate=Decimal("50"))
        first, second = self.accepted_session(), self.accepted_session(doc2)
        self.assertEqual(self.start(first).status_code, 200)
        r = self.start(second)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["error"], "active_session_exists")

    def test_rate_is_locked_at_start(self):
        self.fund("500")
        sid = self.accepted_session()
        self.start(sid)
        self.provider.per_minute_rate = Decimal("80")       # provider raises price mid-call
        self.provider.save()
        self.assertEqual(ConsultationSession.objects.get(pk=sid).per_minute_rate, Decimal("50.00"))

    def test_provider_cannot_start(self):
        sid = self.accepted_session()
        self.as_(self.provider)
        self.assertEqual(self.client.post(f"/api/sessions/{sid}/start/").status_code, 403)

    def test_user_ends_session(self):
        self.fund("500")
        sid = self.accepted_session()
        self.start(sid)
        r = self.end(sid, self.user)
        self.assertEqual(r.data["status"], S.COMPLETED)
        self.assertEqual(r.data["ended_by"], "user")
        self.assertEqual(r.data["end_reason"], "user_ended")
        self.assertIsNotNone(r.data["ended_at"])

    def test_provider_ends_session(self):
        self.fund("500")
        sid = self.accepted_session()
        self.start(sid)
        r = self.end(sid, self.provider)
        self.assertEqual(r.data["ended_by"], "provider")
        self.assertEqual(r.data["end_reason"], "provider_ended")


S = ConsultationSession.Status


class StateMachineUnitTests(SimpleTestCase):
    """Pure logic: no database needed."""

    def test_every_action_rejects_every_status_it_does_not_allow(self):
        for action, (allowed_from, _) in TRANSITIONS.items():
            for current in S.values:
                session = ConsultationSession(status=current)
                if current in allowed_from:
                    apply_transition(session, action)          # must not raise
                else:
                    with self.assertRaises(InvalidTransition):
                        apply_transition(session, action)


class SessionFlowTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("riya", password="x")
        self.provider = User.objects.create_user("doc", password="x", role=User.Role.PROVIDER)
        self.other_provider = User.objects.create_user("doc2", password="x", role=User.Role.PROVIDER)

    # helpers
    def as_(self, who):
        self.client.force_authenticate(who)

    def create_session(self):
        self.as_(self.user)
        r = self.client.post("/api/sessions/")
        self.assertEqual(r.status_code, 201)
        return r.data["id"]

    def assign(self, sid, provider):
        self.as_(self.user)
        return self.client.post(f"/api/sessions/{sid}/assign/", {"provider_id": provider.id})

    def accept(self, sid, provider):
        self.as_(provider)
        return self.client.post(f"/api/sessions/{sid}/accept/")

    # tests
    def test_new_session_is_unassigned(self):
        sid = self.create_session()
        self.assertEqual(ConsultationSession.objects.get(pk=sid).status, S.UNASSIGNED)

    def test_assign_then_accept(self):
        sid = self.create_session()
        self.assertEqual(self.assign(sid, self.provider).data["status"], S.ASSIGNED)
        self.assertEqual(self.accept(sid, self.provider).data["status"], S.ACCEPTED)

    def test_accept_twice_returns_400(self):
        sid = self.create_session()
        self.as_(self.user)
        # provider isn't a participant yet → use a session that is assigned to doc, then try a skip:
        self.assign(sid, self.provider)
        self.accept(sid, self.provider)
        r = self.accept(sid, self.provider)               # accept twice = invalid move
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["error"], "invalid_transition")

    def test_assign_twice_returns_400(self):
        sid = self.create_session()
        self.assign(sid, self.provider)
        r = self.assign(sid, self.other_provider)
        self.assertEqual(r.status_code, 400)

    def test_other_provider_cannot_see_or_accept(self):
        sid = self.create_session()
        self.assign(sid, self.provider)
        self.assertEqual(self.accept(sid, self.other_provider).status_code, 404)

    def test_provider_cannot_create_session(self):
        self.as_(self.provider)
        self.assertEqual(self.client.post("/api/sessions/").status_code, 403)

    def test_assign_non_provider_returns_404(self):
        sid = self.create_session()
        r = self.assign(sid, self.user)                   # riya is not a provider
        self.assertEqual(r.status_code, 404)

    def test_cancelled_session_cannot_be_accepted(self):
        sid = self.create_session()
        self.assign(sid, self.provider)
        self.as_(self.user)
        r = self.client.post(f"/api/sessions/{sid}/cancel/")
        self.assertEqual(r.data["status"], S.CANCELLED)
        self.assertEqual(r.data["end_reason"], "cancelled")
        self.assertEqual(self.accept(sid, self.provider).status_code, 400)

    def test_completed_session_cannot_be_cancelled(self):
        sid = self.create_session()
        ConsultationSession.objects.filter(pk=sid).update(status=S.COMPLETED)
        self.as_(self.user)
        self.assertEqual(self.client.post(f"/api/sessions/{sid}/cancel/").status_code, 400)

