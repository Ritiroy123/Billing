from rest_framework import serializers
from .models import ConsultationSession


class SessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConsultationSession
        fields = [
            "id", "user", "provider", "status", "per_minute_rate",
            "started_at", "ended_at", "billed_minutes", "billed_amount",
            "talk_seconds", "ended_by", "end_reason", "created_at",
        ]
        read_only_fields = fields


class AssignSerializer(serializers.Serializer):
    provider_id = serializers.IntegerField()
