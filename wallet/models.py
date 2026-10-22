from django.conf import settings
from django.db import models
from django.db.models import Q


class Wallet(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="wallet"
    )
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(balance__gte=0), name="wallet_balance_non_negative"),
        ]

    def __str__(self):
        return f"{self.user.username}: ₹{self.balance}"



class WalletTransaction(models.Model):
    class Kind(models.TextChoices):
        CREDIT = "CREDIT", "Credit"
        DEBIT = "DEBIT", "Debit"

    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="transactions")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=50)                  # e.g. "recharge", "session_billing"
    reference = models.CharField(max_length=100, blank=True)  # e.g. recharge ref, "session-5-minute-2"
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="wallet_txn_amount_positive"),
        ]

    def __str__(self):
        return f"{self.kind} ₹{self.amount} ({self.reason})"
