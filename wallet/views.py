
import hmac
from django.conf import settings
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from accounts.permissions import IsUserRole
from . import services
from .models import Wallet
from .serializers import (WalletSerializer, RechargeCreateSerializer,
                          RechargeSerializer, RechargeCallbackSerializer)


class WalletView(generics.RetrieveAPIView):
    serializer_class = WalletSerializer
    permission_classes = [IsUserRole]

    def get_object(self):
        # get_or_create: safety net for users created before the signal existed
        wallet, _ = Wallet.objects.get_or_create(user=self.request.user)
        return wallet




class RechargeView(APIView):
    permission_classes = [IsUserRole]

    def post(self, request):
        s = RechargeCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        recharge = services.initiate_recharge(request.user, s.validated_data["amount"])
        return Response(RechargeSerializer(recharge).data, status=status.HTTP_201_CREATED)


class RechargeCallbackView(APIView):
    """Mock payment-gateway webhook. Called by the 'bank', not by the user."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        secret = request.headers.get("X-Webhook-Secret", "")
        if not hmac.compare_digest(secret, settings.PAYMENT_WEBHOOK_SECRET):
            return Response({"error": "invalid_signature"}, status=status.HTTP_403_FORBIDDEN)

        s = RechargeCallbackSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        recharge, processed = services.process_recharge_callback(**s.validated_data)
        data = RechargeSerializer(recharge).data
        data["already_processed"] = not processed
        return Response(data, status=status.HTTP_200_OK)
