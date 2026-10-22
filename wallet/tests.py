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
