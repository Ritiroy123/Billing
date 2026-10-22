from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Wallet


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_wallet_for_user(sender, instance, created, **kwargs):
    if created and instance.role == instance.Role.USER:
        Wallet.objects.create(user=instance)
