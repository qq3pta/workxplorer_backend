from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.core.exceptions import ValidationError
from django.db.models import Count, DecimalField, ExpressionWrapper, F, FloatField, Func, Q
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework import serializers as drf_serializers
from rest_framework.response import Response

from ..accounts.permissions import (
    IsAuthenticatedAndVerified,
    IsCarrierOrLogistic,
    IsCustomer,
    IsCustomerOrLogistic,
)
from .choices import ModerationStatus
from .models import Cargo, CargoStatus
from .serializers import CargoListSerializer, CargoPublishSerializer


def _swagger(view) -> bool:
    return getattr(view, "swagger_fake_view", False)


class RefreshResponseSerializer(drf_serializers.Serializer):
    detail = drf_serializers.CharField()


class DistanceGeography(ExpressionWrapper):
    function = "ST_Distance"
    output_field = FloatField()

    def __init__(self, origin, dest):
        super().__init__(F(origin) * 1, output_field=self.output_field)
        self.source_expressions = [origin, dest]


class ExtractMinutes(Func):
    """Совместимо с Django 4.2: считает EXTRACT(EPOCH FROM (NOW() - created_at)) / 60.0"""

    template = "EXTRACT(EPOCH FROM (NOW() - %(expressions)s)) / 60.0"
    output_field = FloatField()


# ------------------ Публикация груза ------------------
@extend_schema(tags=["loads"])
class PublishCargoView(generics.CreateAPIView):
    permission_classes = [IsAuthenticatedAndVerified, IsCustomerOrLogistic]
    serializer_class = CargoPublishSerializer
    queryset = Cargo.objects.all()

    def perform_create(self, serializer):
        cargo = serializer.save()
        cargo.update_price_uzs()
        return cargo

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cargo = self.perform_create(serializer)
        data = self.get_serializer(cargo).data
        return Response(
            {
                "message": "Заявка опубликована и отправлена на модерацию",
                "uuid": cargo.uuid,
                "route_km": data.get("route_km"),
                "price_uzs": data.get("price_uzs"),
            },
            status=status.HTTP_201_CREATED,
        )


# ------------------ Детали груза ------------------
@extend_schema(tags=["loads"])
class CargoDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticatedAndVerified, IsCustomer]
    serializer_class = CargoPublishSerializer
    queryset = Cargo.objects.all()

    def get_queryset(self):
        if _swagger(self):
            return Cargo.objects.none()
        return Cargo.objects.filter(customer=self.request.user)

    def get_object(self):
        uuid = self.kwargs.get("uuid")
        if uuid:
            return get_object_or_404(Cargo, uuid=uuid, customer=self.request.user)
        return super().get_object()

    def perform_update(self, serializer):
        obj = serializer.save()
        obj.refreshed_at = timezone.now()
        obj.update_price_uzs()
        obj.save(update_fields=["refreshed_at", "price_uzs"])


# ------------------ Обновление заявки ------------------
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


# ------------------ Мои заявки ------------------
@extend_schema(tags=["loads"])
class MyCargosView(generics.ListAPIView):
    permission_classes = [IsAuthenticatedAndVerified, IsCustomer]
    serializer_class = CargoListSerializer
    queryset = Cargo.objects.all()

    def get_queryset(self):
        if _swagger(self):
            return Cargo.objects.none()
        qs = Cargo.objects.filter(customer=self.request.user).annotate(
            offers_active=Count("offers", filter=Q(offers__is_active=True)),
            path_m=Distance(F("origin_point"), F("dest_point")),
        )
        return (
            qs.annotate(path_km=F("path_m") / 1000.0)
            .select_related("customer")
            .order_by("-refreshed_at", "-created_at")
        )


# ------------------ Борда моих заявок ------------------
@extend_schema(tags=["loads"])
class MyCargosBoardView(MyCargosView):
    def get_queryset(self):
        qs = (
            super()
            .get_queryset()
            .filter(
                status=CargoStatus.POSTED,
                is_hidden=False,
                moderation_status=ModerationStatus.APPROVED,
            )
        )
        p = self.request.query_params
        if p.get("uuid"):
            qs = qs.filter(uuid=p["uuid"])
        if p.get("origin_city"):
            qs = qs.filter(origin_city__iexact=p["origin_city"])
        if p.get("destination_city"):
            qs = qs.filter(destination_city__iexact=p["destination_city"])
        return qs


# ------------------ Публичная доска ------------------
@extend_schema(tags=["loads"])
class PublicLoadsView(generics.ListAPIView):
    permission_classes = [IsAuthenticatedAndVerified, IsCarrierOrLogistic]
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
                offers_active=Count("offers", filter=Q(offers__is_active=True)),
                age_minutes_anno=ExtractMinutes(F("created_at")),
            )
            .select_related("customer")
        )

        p = self.request.query_params

        # --- Фильтры ---
        if p.get("uuid"):
            qs = qs.filter(uuid=p["uuid"])
        if p.get("origin_city"):
            qs = qs.filter(origin_city__iexact=p["origin_city"])
        if p.get("destination_city"):
            qs = qs.filter(destination_city__iexact=p["destination_city"])
        if p.get("load_date"):
            qs = qs.filter(load_date=p["load_date"])
        if p.get("transport_type"):
            qs = qs.filter(transport_type=p["transport_type"])

        if p.get("min_weight"):
            qs = qs.filter(weight_kg__gte=p["min_weight"])
        if p.get("max_weight"):
            qs = qs.filter(weight_kg__lte=p["max_weight"])

        # --- Цена ---
        qs = qs.annotate(
            price_uzs_anno=Coalesce(
                F("price_uzs"),
                F("price_value"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        )
        if p.get("min_price_uzs"):
            qs = qs.filter(price_uzs_anno__gte=p["min_price_uzs"])
        if p.get("max_price_uzs"):
            qs = qs.filter(price_uzs_anno__lte=p["max_price_uzs"])

        # --- Радиусные фильтры ---
        o_lat, o_lng, o_r = p.get("origin_lat"), p.get("origin_lng"), p.get("origin_radius_km")
        if o_lat and o_lng and o_r:
            origin_point = Point(float(o_lng), float(o_lat), srid=4326)
            qs = qs.filter(origin_point__distance_lte=(origin_point, D(km=float(o_r))))
            qs = qs.annotate(origin_dist_km=Distance("origin_point", origin_point) / 1000.0)

        d_lat, d_lng, d_r = p.get("dest_lat"), p.get("dest_lng"), p.get("dest_radius_km")
        if d_lat and d_lng and d_r:
            dest_point = Point(float(d_lng), float(d_lat), srid=4326)
            qs = qs.filter(dest_point__distance_lte=(dest_point, D(km=float(d_r))))

        # --- Сортировка ---
        order = p.get("order")
        allowed = {
            "path_km",
            "-path_km",
            "origin_dist_km",
            "-origin_dist_km",
            "price_uzs_anno",
            "-price_uzs_anno",
            "load_date",
            "-load_date",
        }
        if order in allowed:
            qs = qs.order_by(order)
        else:
            qs = qs.order_by("-refreshed_at", "-created_at")

        return qs


# ------------------ Отмена груза ------------------
@extend_schema(tags=["loads"])
class CargoCancelView(generics.GenericAPIView):
    permission_classes = [IsAuthenticatedAndVerified]
    serializer_class = RefreshResponseSerializer
    queryset = Cargo.objects.all()

    def post(self, request, pk: int):
        if _swagger(self):
            return Response({"detail": "schema"}, status=status.HTTP_200_OK)

        cargo = get_object_or_404(Cargo, pk=pk)
        user_id = request.user.id

        if user_id not in (cargo.customer_id, getattr(cargo, "assigned_carrier_id", None)):
            return Response({"detail": "Нет доступа"}, status=status.HTTP_403_FORBIDDEN)

        if cargo.status in (
            CargoStatus.DELIVERED,
            CargoStatus.COMPLETED,
            CargoStatus.CANCELLED,
        ):
            return Response({"detail": "Статус уже финальный"}, status=status.HTTP_400_BAD_REQUEST)

        cargo.status = CargoStatus.CANCELLED
        cargo.save(update_fields=["status"])
        cargo.offers.update(is_active=False)
        return Response({"detail": "Перевозка отменена"}, status=status.HTTP_200_OK)
