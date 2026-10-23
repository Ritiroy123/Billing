from django.conf import settings
from django.db import models
from django.db.models import Q
import uuid


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
            # DB-level guard: one credit per recharge reference, one debit per session-minute reference
            models.UniqueConstraint(
                fields=["kind", "reference"], condition=~Q(reference=""), name="unique_txn_reference",
            ),
        ]

    def __str__(self):
        return f"{self.kind} ₹{self.amount} ({self.reason})"



    import uuid   # put this at the top of the file


def generate_recharge_reference():
    return f"RCH-{uuid.uuid4().hex}"


class RechargeTransaction(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recharges")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=64, unique=True, default=generate_recharge_reference, editable=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="recharge_amount_positive"),
        ]

    def __str__(self):
        return f"{self.reference} ₹{self.amount} {self.status}"

