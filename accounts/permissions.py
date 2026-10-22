from rest_framework.permissions import BasePermission
from .models import User


class IsUserRole(BasePermission):
    message = "Only USER accounts can perform this action."

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == User.Role.USER


class IsProviderRole(BasePermission):
    message = "Only PROVIDER accounts can perform this action."

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == User.Role.PROVIDER
