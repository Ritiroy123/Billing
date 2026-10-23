from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from .models import User


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = User
        fields = ["id", "username", "password", "role", "per_minute_rate"]

    def validate(self, attrs):
        role = attrs.get("role", User.Role.USER)
        rate = attrs.get("per_minute_rate")
        if role == User.Role.PROVIDER and (rate is None or rate <= 0):
            raise serializers.ValidationError(
                {"per_minute_rate": "Providers must set a positive per-minute rate."}
            )
        if role == User.Role.USER:
            attrs["per_minute_rate"] = None          # users don't have a price
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class MeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "role", "per_minute_rate"]
