from decimal import Decimal
from django.db import IntegrityError, transaction
from rest_framework.test import APITestCase
from accounts.models import User
from .models import Wallet


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



from django.test import TestCase
from common.exceptions import InsufficientBalance, InvalidAmount
from . import services
from .models import WalletTransaction


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
