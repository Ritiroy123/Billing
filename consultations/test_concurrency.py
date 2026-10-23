"""
Real concurrency tests: many threads hit the same wallet / session / recharge at the same instant.

They prove the row locks (select_for_update) and DB constraints actually prevent double charges,
double credits and negative balances. They need PostgreSQL (SQLite has no row-level locks and
allows only one writer at a time), so they are skipped on other databases.
"""
import threading
import unittest
from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone

from accounts.models import User
from common.exceptions import ActiveSessionExists, InsufficientBalance
from wallet import services as wallet_services
from wallet.models import RechargeTransaction, WalletTransaction
from . import services
from .models import BillingRecord, ConsultationSession

S = ConsultationSession.Status
THREADS = 10


def run_in_parallel(fn, n=THREADS):
    """Run fn in n threads released at the same moment. Returns a list of ("ok", value) / ("error", exc)."""
    barrier = threading.Barrier(n)
    results, results_lock = [], threading.Lock()

    def worker():
        try:
            barrier.wait()                       # every thread starts together
            outcome = ("ok", fn())
        except Exception as exc:                 # collect, don't crash the thread
            outcome = ("error", exc)
        finally:
            connection.close()                   # each thread has its own DB connection
        with results_lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


@unittest.skipUnless(connection.vendor == "postgresql", "needs PostgreSQL row-level locks")
class ConcurrencyTests(TransactionTestCase):
    """TransactionTestCase: data is really committed, so other threads' connections can see it."""

    def setUp(self):
        self.user = User.objects.create_user("riya", password="x")
        self.provider = User.objects.create_user(
            "doc", password="x", role=User.Role.PROVIDER, per_minute_rate=Decimal("50"))

    def balance(self):
        self.user.wallet.refresh_from_db()
        return self.user.wallet.balance

    def test_parallel_duplicate_webhooks_credit_once(self):
        recharge = wallet_services.initiate_recharge(self.user, Decimal("500"))

        results = run_in_parallel(
            lambda: wallet_services.process_recharge_callback(recharge.reference, "success"))

        processed_now = [value[1] for kind, value in results if kind == "ok"]
        self.assertEqual(len(processed_now), THREADS)          # nobody crashed
        self.assertEqual(processed_now.count(True), 1)         # exactly one thread did the work
        self.assertEqual(self.balance(), Decimal("500.00"))
        self.assertEqual(WalletTransaction.objects.filter(reference=recharge.reference).count(), 1)
        self.assertEqual(RechargeTransaction.objects.get(pk=recharge.pk).status, "success")

    def test_parallel_billing_charges_each_minute_once(self):
        wallet_services.credit(self.user, Decimal("500"), reason="test")
        session = ConsultationSession.objects.create(
            user=self.user, provider=self.provider, status=S.IN_PROGRESS,
            per_minute_rate=Decimal("50"),
            started_at=timezone.now() - timedelta(minutes=3, seconds=10),
        )

        results = run_in_parallel(lambda: services.bill_session(session.pk))

        self.assertTrue(all(kind == "ok" for kind, _ in results))
        session.refresh_from_db()
        self.assertEqual(session.billed_minutes, 3)
        self.assertEqual(self.balance(), Decimal("350.00"))    # 500 − 3 × 50, not 500 − 30 × 50
        self.assertEqual(BillingRecord.objects.filter(session=session).count(), 3)

    def test_parallel_debits_never_go_negative(self):
        wallet_services.credit(self.user, Decimal("100"), reason="test")

        results = run_in_parallel(
            lambda: wallet_services.debit(self.user, Decimal("30"), reason="session_billing"))

        succeeded = [v for kind, v in results if kind == "ok"]
        refused = [v for kind, v in results if kind == "error"]
        self.assertEqual(len(succeeded), 3)                    # 3 × 30 = 90 fits in 100
        self.assertTrue(all(isinstance(e, InsufficientBalance) for e in refused))
        self.assertEqual(self.balance(), Decimal("10.00"))

    def test_parallel_starts_allow_only_one_active_session(self):
        wallet_services.credit(self.user, Decimal("1000"), reason="test")
        providers = [self.provider] + [
            User.objects.create_user(f"doc{i}", password="x", role=User.Role.PROVIDER,
                                     per_minute_rate=Decimal("50"))
            for i in range(1, 5)
        ]
        session_ids = [
            ConsultationSession.objects.create(user=self.user, provider=p, status=S.ACCEPTED).pk
            for p in providers
        ]
        queue, queue_lock = list(session_ids), threading.Lock()

        def start_one():                                       # each thread starts a different session
            with queue_lock:
                sid = queue.pop()
            return services.start(sid, self.user)

        results = run_in_parallel(start_one, n=len(session_ids))

        started = [v for kind, v in results if kind == "ok"]
        refused = [v for kind, v in results if kind == "error"]
        self.assertEqual(len(started), 1)
        self.assertTrue(all(isinstance(e, ActiveSessionExists) for e in refused))
        self.assertEqual(
            ConsultationSession.objects.filter(user=self.user, status=S.IN_PROGRESS).count(), 1)
