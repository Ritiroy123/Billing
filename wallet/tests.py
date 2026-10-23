from decimal import Decimal
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APITestCase
from accounts.models import User
from common.exceptions import InsufficientBalance, InvalidAmount
from . import services
from .models import RechargeTransaction, Wallet, WalletTransaction


class WalletTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("riya", password="x")
        self.provider = User.objects.create_user("doc", password="x", role=User.Role.PROVIDER)

    def test_wallet_auto_created_for_user_only(self):
        self.assertEqual(self.user.wallet.balance, Decimal("0.00"))
        self.assertFalse(Wallet.objects.filter(user=self.provider).exists())

    def test_view_balance(self):
        self.client.force_authenticate(self.user)
        r = self.client.get("/api/wallet/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["balance"], "0.00")

    def test_provider_cannot_view_wallet(self):
        self.client.force_authenticate(self.provider)
        self.assertEqual(self.client.get("/api/wallet/").status_code, 403)

    def test_anonymous_gets_401(self):
        self.assertEqual(self.client.get("/api/wallet/").status_code, 401)

    def test_db_rejects_negative_balance(self):
        wallet = self.user.wallet
        wallet.balance = Decimal("-1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                wallet.save()


class WalletServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("amit", password="x")

    def test_credit_adds_money_and_writes_ledger(self):
        services.credit(self.user, Decimal("500"), reason="recharge", reference="R1")
        self.user.wallet.refresh_from_db()
        self.assertEqual(self.user.wallet.balance, Decimal("500.00"))
        txn = WalletTransaction.objects.get()
        self.assertEqual(txn.kind, "CREDIT")
        self.assertEqual(txn.balance_after, Decimal("500.00"))

    def test_debit_takes_money(self):
        services.credit(self.user, Decimal("500"), reason="recharge")
        services.debit(self.user, Decimal("50"), reason="session_billing")
        self.user.wallet.refresh_from_db()
        self.assertEqual(self.user.wallet.balance, Decimal("450.00"))

    def test_debit_exact_balance_reaches_zero(self):
        services.credit(self.user, Decimal("50"), reason="recharge")
        services.debit(self.user, Decimal("50"), reason="session_billing")
        self.user.wallet.refresh_from_db()
        self.assertEqual(self.user.wallet.balance, Decimal("0.00"))

    def test_debit_more_than_balance_is_refused(self):
        services.credit(self.user, Decimal("40"), reason="recharge")
        with self.assertRaises(InsufficientBalance):
            services.debit(self.user, Decimal("50"), reason="session_billing")
        self.user.wallet.refresh_from_db()
        self.assertEqual(self.user.wallet.balance, Decimal("40.00"))     # unchanged
        self.assertEqual(WalletTransaction.objects.count(), 1)           # only the credit

    def test_invalid_amounts_are_refused(self):
        for bad in [Decimal("0"), Decimal("-10"), 50.0]:
            with self.assertRaises(InvalidAmount):
                services.credit(self.user, bad, reason="recharge")

    def test_db_rejects_second_credit_with_same_reference(self):
        services.credit(self.user, Decimal("500"), reason="recharge", reference="RCH-1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                services.credit(self.user, Decimal("500"), reason="recharge", reference="RCH-1")
        self.user.wallet.refresh_from_db()
        self.assertEqual(self.user.wallet.balance, Decimal("500.00"))


class RechargeTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("riya", password="x")
        self.client.force_authenticate(self.user)

    def start_recharge(self, amount="500"):
        r = self.client.post("/api/wallet/recharge/", {"amount": amount})
        self.assertEqual(r.status_code, 201)
        return r.data["reference"]

    def callback(self, reference, status="success", secret="dev-webhook-secret"):
        return self.client.post(
            "/api/wallet/recharge/callback/",
            {"reference": reference, "status": status},
            HTTP_X_WEBHOOK_SECRET=secret,
        )

    def balance(self):
        self.user.wallet.refresh_from_db()
        return self.user.wallet.balance

    def test_initiate_creates_pending_without_crediting(self):
        ref = self.start_recharge()
        self.assertEqual(RechargeTransaction.objects.get(reference=ref).status, "pending")
        self.assertEqual(self.balance(), Decimal("0.00"))

    def test_success_callback_credits_wallet(self):
        ref = self.start_recharge()
        r = self.callback(ref)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "success")
        self.assertEqual(self.balance(), Decimal("500.00"))

    def test_duplicate_success_callback_credits_only_once(self):      # REQUIRED TEST #5
        ref = self.start_recharge()
        first = self.callback(ref)
        second = self.callback(ref)
        self.assertFalse(first.data["already_processed"])
        self.assertTrue(second.data["already_processed"])
        self.assertEqual(self.balance(), Decimal("500.00"))           # not 1000
        self.assertEqual(WalletTransaction.objects.filter(reference=ref).count(), 1)

    def test_failed_callback_does_not_credit_and_is_final(self):
        ref = self.start_recharge()
        self.callback(ref, status="failed")
        self.callback(ref, status="success")                          # late success is ignored
        self.assertEqual(RechargeTransaction.objects.get(reference=ref).status, "failed")
        self.assertEqual(self.balance(), Decimal("0.00"))

    def test_callback_with_wrong_secret_is_rejected(self):
        ref = self.start_recharge()
        self.assertEqual(self.callback(ref, secret="hacker").status_code, 403)
        self.assertEqual(self.balance(), Decimal("0.00"))

    def test_unknown_reference_returns_404(self):
        self.assertEqual(self.callback("RCH-doesnotexist").status_code, 404)

    def test_invalid_amount_returns_400(self):
        r = self.client.post("/api/wallet/recharge/", {"amount": "0"})
        self.assertEqual(r.status_code, 400)
