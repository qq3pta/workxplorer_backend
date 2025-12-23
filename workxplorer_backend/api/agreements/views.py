from django.db import models
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from .models import Agreement
from .permissions import IsAgreementParticipant
from .serializers import (
    AgreementActionSerializer,
    AgreementListSerializer,
    AgreementDetailSerializer,
)


class AgreementViewSet(ReadOnlyModelViewSet):
    """
    Вкладка «Соглашения»
    """

    permission_classes = [IsAgreementParticipant]
    queryset = Agreement.objects.all()

    # 🔹 ВАЖНО: правильный выбор сериализатора
    def get_serializer_class(self):
        if self.action == "list":
            return AgreementListSerializer
        if self.action == "retrieve":
            return AgreementDetailSerializer
        return AgreementActionSerializer

    # 🔹 ФИЛЬТРАЦИЯ ПО РОЛЯМ
    def get_queryset(self):
        u = self.request.user
        qs = Agreement.objects.select_related("offer", "offer__cargo")

        qs = qs.filter(status=Agreement.Status.PENDING)

        if u.role == "CUSTOMER":
            return qs.filter(offer__cargo__customer=u)

        if u.role == "CARRIER":
            return qs.filter(offer__carrier=u)

        if u.role == "LOGISTIC":
            return qs.filter(
                models.Q(offer__logistic=u)
                | models.Q(offer__intermediary=u)
                | models.Q(offer__cargo__customer=u)
                | models.Q(offer__cargo__created_by=u)
            ).distinct()

        return qs.none()

    # ---------------------------
    # ACCEPT
    # ---------------------------
    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        agreement = self.get_object()
        agreement.accept_by(request.user)
        return Response(
            {"detail": "Соглашение принято"},
            status=status.HTTP_200_OK,
        )

    # ---------------------------
    # REJECT
    # ---------------------------
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        agreement = self.get_object()
        agreement.reject(by_user=request.user)
        return Response(
            {"detail": "Соглашение отклонено"},
            status=status.HTTP_200_OK,
        )
