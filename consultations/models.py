from django.conf import settings
from django.db import models
from django.db.models import Q


class ConsultationSession(models.Model):
    class Status(models.TextChoices):
        UNASSIGNED = "unassigned", "Unassigned"
        ASSIGNED = "assigned", "Assigned"
        ACCEPTED = "accepted_by_provider", "Accepted by provider"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    class EndedBy(models.TextChoices):
        USER = "user", "User"
        PROVIDER = "provider", "Provider"
        SYSTEM = "system", "System"

    class EndReason(models.TextChoices):
        USER_ENDED = "user_ended", "Ended by user"
        PROVIDER_ENDED = "provider_ended", "Ended by provider"
        INSUFFICIENT_BALANCE = "insufficient_balance", "Insufficient balance"
        CANCELLED = "cancelled", "Cancelled"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                             related_name="sessions_as_user")
    provider = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                 related_name="sessions_as_provider", null=True, blank=True)
    status = models.CharField(max_length=25, choices=Status.choices, default=Status.UNASSIGNED)

    # Billing fields (used from Step 8 onwards)
    per_minute_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    billed_minutes = models.PositiveIntegerField(default=0)
    billed_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    ended_by = models.CharField(max_length=10, choices=EndedBy.choices, blank=True)
    end_reason = models.CharField(max_length=25, choices=EndReason.choices, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"], condition=Q(status="in_progress"),
                name="one_active_session_per_user",
            ),
        ]

    def __str__(self):
        return f"Session {self.pk} ({self.status})"
