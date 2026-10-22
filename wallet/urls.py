from django.urls import path
from .views import WalletView

urlpatterns = [
    path("", WalletView.as_view()),
]
