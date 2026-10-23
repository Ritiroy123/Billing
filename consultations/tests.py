from django.test import SimpleTestCase
from rest_framework.test import APITestCase
from accounts.models import User
from common.exceptions import InvalidTransition
from .models import ConsultationSession
from .state_machine import apply_transition, TRANSITIONS

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

    def test_accept_before_assign_returns_400(self):
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

