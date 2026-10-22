from rest_framework import generics
from accounts.permissions import IsUserRole
from .models import Wallet
from .serializers import WalletSerializer


class WalletView(generics.RetrieveAPIView):
    serializer_class = WalletSerializer
    permission_classes = [IsUserRole]

    def get_object(self):
        # get_or_create: safety net for users created before the signal existed
        wallet, _ = Wallet.objects.get_or_create(user=self.request.user)
        return wallet
