from rest_framework import serializers
from .models import Wallet


class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = ["balance", "updated_at"]
        read_only_fields = fields


from decimal import Decimal
from .models import Wallet, RechargeTransaction


class RechargeCreateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("1.00"))


class RechargeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RechargeTransaction
        fields = ["reference", "amount", "status", "created_at", "completed_at"]
        read_only_fields = fields


class RechargeCallbackSerializer(serializers.Serializer):
    reference = serializers.CharField(max_length=64)
    status = serializers.ChoiceField(choices=[
        RechargeTransaction.Status.SUCCESS, RechargeTransaction.Status.FAILED,
    ])
