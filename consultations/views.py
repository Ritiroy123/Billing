from django.db.models import Q
from rest_framework import permissions, status, viewsets, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from accounts.permissions import IsUserRole, IsProviderRole
from . import services
from .models import ConsultationSession
from .serializers import SessionSerializer, AssignSerializer


class SessionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = SessionSerializer

    def get_queryset(self):
        me = self.request.user
        return ConsultationSession.objects.filter(Q(user=me) | Q(provider=me))

    def get_permissions(self):
        if self.action in ("create", "assign", "start"):
            return [IsUserRole()]
        if self.action == "accept":
            return [IsProviderRole()]
        return [permissions.IsAuthenticated()]

    def create(self, request):
        session = services.create_session(request.user)
        return Response(SessionSerializer(session).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        s = AssignSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        session = services.assign(self.get_object().pk, request.user, s.validated_data["provider_id"])
        return Response(SessionSerializer(session).data)

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        session = services.accept(self.get_object().pk, request.user)
        return Response(SessionSerializer(session).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        session = services.cancel(self.get_object().pk, request.user)
        return Response(SessionSerializer(session).data)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        session = services.start(self.get_object().pk, request.user)
        return Response(SessionSerializer(session).data)

    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        session = services.end(self.get_object().pk, request.user)
        return Response(SessionSerializer(session).data)


