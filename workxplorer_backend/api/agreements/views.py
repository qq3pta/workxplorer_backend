from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from common.ws_utils import to_ws_safe
from django.db import models
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from .models import Agreement
from .permissions import IsAgreementParticipant
from .serializers import (
    AgreementActionSerializer,
    AgreementDetailSerializer,
    AgreementListSerializer,
)


class AgreementViewSet(ReadOnlyModelViewSet):
    """
    Вкладка «Соглашения»
    """

    permission_classes = [IsAgreementParticipant]
    queryset = Agreement.objects.all()

    def get_serializer_class(self):
        if self.action == "list":
            return AgreementListSerializer
        if self.action == "retrieve":
            return AgreementDetailSerializer
        return AgreementActionSerializer

    #  ФИЛЬТРАЦИЯ ПО РОЛЯМ
    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Agreement.objects.none()

        u = self.request.user
        now = timezone.now()

        qs = Agreement.objects.select_related("offer", "offer__cargo").filter(
            status=Agreement.Status.PENDING,
            expires_at__gt=now,
        )

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

        channel_layer = get_channel_layer()
        agreement.refresh_from_db()
        payload = AgreementDetailSerializer(agreement, context={"request": request}).data

        participants = {
            agreement.offer.cargo.customer_id,
            agreement.offer.carrier_id,
            agreement.offer.logistic_id,
            agreement.offer.intermediary_id,
        }

        for user_id in filter(None, participants):
            message = {
                "type": "notify",
                "data": {
                    "event": "agreement_accepted",
                    "order": payload,
                },
            }

            async_to_sync(channel_layer.group_send)(
                f"user_{user_id}",
                to_ws_safe(message),
            )

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

        channel_layer = get_channel_layer()
        agreement.refresh_from_db()

        payload = AgreementDetailSerializer(agreement, context={"request": request}).data

        participants = {
            agreement.offer.cargo.customer_id,
            agreement.offer.carrier_id,
            agreement.offer.logistic_id,
            agreement.offer.intermediary_id,
        }

        for user_id in filter(None, participants):
            message = {
                "type": "notify",
                "data": {
                    "event": "agreement_rejected",
                    "order": payload,
                },
            }

            async_to_sync(channel_layer.group_send)(
                f"user_{user_id}",
                to_ws_safe(message),
            )

        return Response(
            {"detail": "Соглашение отклонено"},
            status=status.HTTP_200_OK,
        )
