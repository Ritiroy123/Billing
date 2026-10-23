from decimal import Decimal
from django.db import transaction
from common.exceptions import InsufficientBalance, InvalidAmount
from .models import Wallet, WalletTransaction


def _check_amount(amount):
    if not isinstance(amount, Decimal) or amount <= 0:
        raise InvalidAmount("Amount must be a positive Decimal.")


@transaction.atomic
def credit(user, amount, reason, reference=""):
    _check_amount(amount)
    wallet = Wallet.objects.select_for_update().get(user=user)   # lock the row
    wallet.balance += amount
    wallet.save(update_fields=["balance", "updated_at"])
    WalletTransaction.objects.create(
        wallet=wallet, kind=WalletTransaction.Kind.CREDIT, amount=amount,
        balance_after=wallet.balance, reason=reason, reference=reference,
    )
    return wallet


@transaction.atomic
def debit(user, amount, reason, reference=""):
    _check_amount(amount)
    wallet = Wallet.objects.select_for_update().get(user=user)   # lock the row
    if wallet.balance < amount:
        raise InsufficientBalance(
            f"Balance ₹{wallet.balance} is less than required ₹{amount}."
        )
    wallet.balance -= amount
    wallet.save(update_fields=["balance", "updated_at"])
    WalletTransaction.objects.create(
        wallet=wallet, kind=WalletTransaction.Kind.DEBIT, amount=amount,
        balance_after=wallet.balance, reason=reason, reference=reference,
    )
    return wallet


from django.utils import timezone
from common.exceptions import InsufficientBalance, InvalidAmount, NotFound
from .models import Wallet, WalletTransaction, RechargeTransaction


def initiate_recharge(user, amount):
    _check_amount(amount)
    return RechargeTransaction.objects.create(user=user, amount=amount)


@transaction.atomic
def process_recharge_callback(reference, status):
    """Idempotent: the same callback may arrive many times; the wallet is credited once."""
    try:
        recharge = RechargeTransaction.objects.select_for_update().get(reference=reference)
    except RechargeTransaction.DoesNotExist:
        raise NotFound(f"No recharge with reference {reference}.")

    if recharge.status != RechargeTransaction.Status.PENDING:
        return recharge, False                 # already processed → do nothing

    recharge.status = status
    recharge.completed_at = timezone.now()
    recharge.save(update_fields=["status", "completed_at"])

    if status == RechargeTransaction.Status.SUCCESS:
        credit(recharge.user, recharge.amount, reason="recharge", reference=recharge.reference)

    return recharge, True                      # True = we processed it now
