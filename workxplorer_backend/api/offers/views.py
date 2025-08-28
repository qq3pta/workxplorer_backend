from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError, PermissionDenied

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from ..accounts.permissions import IsAuthenticatedAndVerified, IsCarrier, IsCustomer
from api.loads.models import Cargo
from .models import Offer
from .serializers import (
    OfferCreateSerializer,
    OfferShortSerializer,
    OfferDetailSerializer,
)


@extend_schema(tags=["offers"])
class CreateOfferView(generics.CreateAPIView):
    """Создать оффер (только Перевозчик/Логист)."""
    permission_classes = [IsAuthenticatedAndVerified, IsCarrier]
    serializer_class = OfferCreateSerializer
    queryset = Offer.objects.all()

    def perform_create(self, serializer):
        serializer.save()


@extend_schema(tags=["offers"], responses=OfferShortSerializer)
class MyOffersView(generics.ListAPIView):
    """Мои офферы (как Перевозчик)."""
    permission_classes = [IsAuthenticatedAndVerified, IsCarrier]
    serializer_class = OfferShortSerializer

    def get_queryset(self):
        return Offer.objects.filter(carrier=self.request.user).order_by("-created_at")


@extend_schema(tags=["offers"], responses=OfferShortSerializer)
class IncomingOffersView(generics.ListAPIView):
    """Входящие офферы на мои грузы (как Заказчик/Логист)."""
    permission_classes = [IsAuthenticatedAndVerified, IsCustomer]
    serializer_class = OfferShortSerializer

    def get_queryset(self):
        # все офферы на заявки текущего пользователя
        return Offer.objects.filter(cargo__customer=self.request.user, is_active=True).order_by("-created_at")


@extend_schema(tags=["offers"], responses=OfferDetailSerializer)
class OfferDetailView(generics.RetrieveAPIView):
    """Детали оффера (видит перевозчик – автор; или владелец груза/логист)."""
    permission_classes = [IsAuthenticatedAndVerified]
    serializer_class = OfferDetailSerializer
    queryset = Offer.objects.select_related("cargo", "carrier")

    def get_object(self):
        obj = super().get_object()
        u = self.request.user
        if u.id not in (obj.carrier_id, obj.cargo.customer_id) and not getattr(u, "is_logistic", False):
            raise PermissionDenied("Нет доступа к офферу")
        return obj


@extend_schema(tags=["offers"])
class OfferAcceptView(APIView):
    """Акцепт оффера стороной (перевозчик/заказчик). При взаимном акцепте создаётся Shipment."""
    permission_classes = [IsAuthenticatedAndVerified]

    def post(self, request, pk: int):
        offer = get_object_or_404(Offer.objects.select_related("cargo"), pk=pk, is_active=True)
        try:
            offer.accept_by(request.user)
        except PermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
        return Response(
            {"detail": "Принято", "accepted_by_customer": offer.accepted_by_customer, "accepted_by_carrier": offer.accepted_by_carrier},
            status=status.HTTP_200_OK,
        )


@extend_schema(tags=["offers"])
class OfferRejectView(APIView):
    """Отклонить/снять оффер любой из сторон (становится неактивным)."""
    permission_classes = [IsAuthenticatedAndVerified]

    def post(self, request, pk: int):
        offer = get_object_or_404(Offer, pk=pk, is_active=True)
        try:
            offer.reject_by(request.user)
        except PermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
        return Response({"detail": "Отклонено"}, status=status.HTTP_200_OK)