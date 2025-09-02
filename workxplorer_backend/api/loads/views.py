from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError
from django.db.models import Count, Q

from rest_framework import generics, status
from rest_framework import serializers as drf_serializers
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from .models import Cargo, CargoStatus
from .choices import ModerationStatus
from .serializers import CargoPublishSerializer, CargoListSerializer
from ..accounts.permissions import IsAuthenticatedAndVerified, IsCustomer, IsCarrier  # ← добавили IsCarrier


def _swagger(view) -> bool:
    """True, когда drf-spectacular генерирует схему и у вьюхи нет реального request.user."""
    return getattr(view, "swagger_fake_view", False)


class RefreshResponseSerializer(drf_serializers.Serializer):
    """Простой сериализатор для ответа refresh."""
    detail = drf_serializers.CharField()


@extend_schema(tags=["loads"])
class PublishCargoView(generics.CreateAPIView):
    permission_classes = [IsAuthenticatedAndVerified, IsCustomer]
    serializer_class = CargoPublishSerializer
    queryset = Cargo.objects.all()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cargo = serializer.save()
        return Response(
            {"message": "Заявка успешно опубликована и отправлена на модерацию", "id": cargo.id},
            status=status.HTTP_201_CREATED,
            headers=self.get_success_headers(serializer.data),
        )


@extend_schema(tags=["loads"])
class CargoDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticatedAndVerified, IsCustomer]
    serializer_class = CargoPublishSerializer
    queryset = Cargo.objects.all()

    def get_queryset(self):
        if _swagger(self):
            return Cargo.objects.none()
        return Cargo.objects.filter(customer=self.request.user)

    def perform_update(self, serializer):
        obj = serializer.save()
        obj.refreshed_at = timezone.now()
        obj.save(update_fields=["refreshed_at"])


@extend_schema(tags=["loads"], responses=RefreshResponseSerializer)
class CargoRefreshView(generics.GenericAPIView):
    permission_classes = [IsAuthenticatedAndVerified, IsCustomer]
    serializer_class = RefreshResponseSerializer
    queryset = Cargo.objects.all()

    def post(self, request, pk: int):
        if _swagger(self):
            return Response({"detail": "schema"}, status=status.HTTP_200_OK)

        obj = get_object_or_404(Cargo, pk=pk, customer=request.user)
        try:
            obj.bump()
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        return Response({"detail": "Обновлено"}, status=status.HTTP_200_OK)


@extend_schema(tags=["loads"])
class MyCargosView(generics.ListAPIView):
    permission_classes = [IsAuthenticatedAndVerified, IsCustomer]
    serializer_class = CargoListSerializer
    queryset = Cargo.objects.all()

    def get_queryset(self):
        if _swagger(self):
            return Cargo.objects.none()
        return (
            Cargo.objects
            .filter(customer=self.request.user)
            .order_by("-refreshed_at", "-created_at")
        )


@extend_schema(tags=["loads"])
class MyCargosBoardView(generics.ListAPIView):
    permission_classes = [IsAuthenticatedAndVerified, IsCustomer]
    serializer_class = CargoListSerializer
    queryset = Cargo.objects.all()

    def get_queryset(self):
        if _swagger(self):
            return Cargo.objects.none()

        qs = Cargo.objects.filter(
            customer=self.request.user,
            status=CargoStatus.POSTED,
            is_hidden=False,
            moderation_status=ModerationStatus.APPROVED,
        )

        p = self.request.query_params
        if p.get("origin_city"):
            qs = qs.filter(origin_city__iexact=p["origin_city"])
        if p.get("destination_city"):
            qs = qs.filter(destination_city__iexact=p["destination_city"])
        if p.get("load_date"):
            qs = qs.filter(load_date=p["load_date"])
        if p.get("transport_type"):
            qs = qs.filter(transport_type=p["transport_type"])
        if p.get("id"):
            qs = qs.filter(id=p["id"])

        return qs.order_by("-refreshed_at", "-created_at")


@extend_schema(tags=["loads"])
class PublicLoadsView(generics.ListAPIView):
    """
    Публичная доска: видна Перевозчику/Логисту.
    Показывает только одобренные, не скрытые и активные заявки.
    Поддерживает фильтры по макету.
    """
    permission_classes = [IsAuthenticatedAndVerified, IsCarrier]
    serializer_class = CargoListSerializer
    queryset = Cargo.objects.all()

    def get_queryset(self):
        qs = (
            Cargo.objects.filter(
                is_hidden=False,
                moderation_status=ModerationStatus.APPROVED,
                status=CargoStatus.POSTED,
            )
            .annotate(
                offers_active=Count("offers", filter=Q(offers__is_active=True))
            )
            .annotate(has_offers=Q(offers_active__gt=0))
        )

        p = self.request.query_params
        if p.get("origin_city"):
            qs = qs.filter(origin_city__iexact=p["origin_city"])
        if p.get("destination_city"):
            qs = qs.filter(destination_city__iexact=p["destination_city"])
        if p.get("load_date"):
            qs = qs.filter(load_date=p["load_date"])
        if p.get("transport_type"):
            qs = qs.filter(transport_type=p["transport_type"])
        if p.get("id"):
            qs = qs.filter(id=p["id"])

        # вес (тоннаж)
        if p.get("min_weight"):
            qs = qs.filter(weight_kg__gte=p["min_weight"])
        if p.get("max_weight"):
            qs = qs.filter(weight_kg__lte=p["max_weight"])

        # ценовые фильтры (без конвертации)
        if p.get("min_price"):
            qs = qs.filter(price_value__gte=p["min_price"])
        if p.get("max_price"):
            qs = qs.filter(price_value__lte=p["max_price"])

        # фильтр по валюте (если поле есть в модели)
        price_currency = p.get("price_currency")
        if price_currency and any(f.name == "price_currency" for f in Cargo._meta.get_fields()):
            qs = qs.filter(price_currency=price_currency)

        # фильтр по наличию предложений
        has_offers = p.get("has_offers")
        if has_offers in {"true", "1"}:
            qs = qs.filter(offers_active__gt=0)
        elif has_offers in {"false", "0"}:
            qs = qs.filter(offers_active=0)

        return qs.order_by("-refreshed_at", "-created_at")