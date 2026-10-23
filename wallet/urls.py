from django.urls import path
from .views import WalletView, RechargeView, RechargeCallbackView

urlpatterns = [
    path("", WalletView.as_view()),
    path("recharge/", RechargeView.as_view()),
    path("recharge/callback/", RechargeCallbackView.as_view()),
]
