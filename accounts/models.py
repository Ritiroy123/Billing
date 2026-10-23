from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    
    class Role(models.TextChoices):
        USER = "USER", "User"
        PROVIDER = "PROVIDER", "Provider"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.USER)
    per_minute_rate = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Provider's price per minute. Empty for USER accounts.",
    )


    @property
    def is_provider(self):
        return self.role == self.Role.PROVIDER

    def __str__(self):
        return f"{self.username} ({self.role})"

