from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.core.exceptions import ValidationError
from django.db.models import (
    Avg,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    FloatField,
    Func,
    Q,
    Value,
)
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
    """Django 4.2-совместимо: EXTRACT(EPOCH FROM (NOW() - field)) / 60.0"""

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

    def post(self, request, uuid: str):
        if _swagger(self):
            return Response({"detail": "schema"}, status=status.HTTP_200_OK)

        obj = get_object_or_404(Cargo, uuid=uuid, customer=request.user)
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

        qs = (
            Cargo.objects.filter(customer=self.request.user)
            .annotate(
                offers_active=Count("offers", filter=Q(offers__is_active=True)),
                path_m=Distance(F("origin_point"), F("dest_point")),
            )
            .annotate(
                path_km=F("path_m") / 1000.0,
                price_uzs_anno=Coalesce(
                    F("price_uzs"),
                    F("price_value"),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                ),
                company_rating=Avg("customer__ratings_received__score"),
            )
            .select_related("customer")
        )

        p = self.request.query_params

        # Базовые фильтры
        if p.get("uuid"):
            qs = qs.filter(uuid=p["uuid"])
        if p.get("origin_city"):
            qs = qs.filter(origin_city__iexact=p["origin_city"])
        if p.get("destination_city"):
            qs = qs.filter(destination_city__iexact=p["destination_city"])
        if p.get("load_date"):
            qs = qs.filter(load_date=p["load_date"])
        if p.get("load_date_from"):
            qs = qs.filter(load_date__gte=p["load_date_from"])
        if p.get("load_date_to"):
            qs = qs.filter(load_date__lte=p["load_date_to"])

        # Симметрия с публичной: транспорт / вес / оси / объём / цена
        if p.get("transport_type"):
            qs = qs.filter(transport_type=p["transport_type"])
        if p.get("min_weight"):
            qs = qs.filter(weight_kg__gte=p["min_weight"])
        if p.get("max_weight"):
            qs = qs.filter(weight_kg__lte=p["max_weight"])
        if p.get("axles_min"):
            qs = qs.filter(axles__gte=p["axles_min"])
        if p.get("axles_max"):
            qs = qs.filter(axles__lte=p["axles_max"])
        if p.get("volume_min"):
            qs = qs.filter(volume_m3__gte=p["volume_min"])
        if p.get("volume_max"):
            qs = qs.filter(volume_m3__lte=p["volume_max"])
        if p.get("min_price_uzs"):
            qs = qs.filter(price_uzs_anno__gte=p["min_price_uzs"])
        if p.get("max_price_uzs"):
            qs = qs.filter(price_uzs_anno__lte=p["max_price_узs"])

        # Радиусные фильтры (как на публичной)
        o_lat, o_lng, o_r = p.get("origin_lat"), p.get("origin_lng"), p.get("origin_radius_km")
        if o_lat and o_lng and o_r:
            try:
                origin_point = Point(float(o_lng), float(o_lat), srid=4326)
                radius_km = float(o_r)
                qs = qs.filter(origin_point__distance_lte=(origin_point, D(km=radius_km)))
                qs = qs.annotate(
                    origin_dist_km=Distance("origin_point", origin_point) / 1000.0,
                    origin_radius_km=Value(radius_km, output_field=FloatField()),
                )
            except (TypeError, ValueError):
                pass

        d_lat, d_lng, d_r = p.get("dest_lat"), p.get("dest_lng"), p.get("dest_radius_km")
        if d_lat and d_lng and d_r:
            try:
                dest_point = Point(float(d_lng), float(d_lat), srid=4326)
                radius_km2 = float(d_r)
                qs = qs.filter(dest_point__distance_lte=(dest_point, D(km=radius_km2)))
                qs = qs.annotate(
                    dest_radius_km=Value(radius_km2, output_field=FloatField()),
                )
            except (TypeError, ValueError):
                pass

        # Поиск по компании/аккаунту
        q = p.get("company") or p.get("q")
        if q:
            qs = qs.filter(
                Q(customer__company_name__icontains=q)
                | Q(customer__username__icontains=q)
                | Q(customer__email__icontains=q)
            )

        # Фильтры по контактам владельца
        if p.get("customer_email"):
            qs = qs.filter(customer__email__iexact=p["customer_email"])
        if p.get("customer_phone"):
            qs = qs.filter(
                Q(customer__phone__icontains=p["customer_phone"])
                | Q(customer__phone_number__icontains=p["customer_phone"])
            )

        # Сортировки
        allowed = {
            "path_km",
            "-path_km",
            "origin_dist_km",
            "-origin_dist_km",
            "price_uzs_anno",
            "-price_uzs_anno",
            "load_date",
            "-load_date",
            "axles",
            "-axles",
            "volume_m3",
            "-volume_m3",
        }
        order = p.get("order")
        if order in allowed:
            return qs.order_by(order)
        return qs.order_by("-refreshed_at", "-created_at")


# ------------------ Борда моих заявок ------------------
@extend_schema(tags=["loads"])
class MyCargosBoardView(MyCargosView):
    permission_classes = [IsAuthenticatedAndVerified, IsCustomerOrLogistic]

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
                age_minutes_anno=ExtractMinutes(F("refreshed_at")),
                path_m=Distance(F("origin_point"), F("dest_point")),
            )
            .annotate(
                path_km=F("path_m") / 1000.0,
                price_uzs_anno=Coalesce(
                    F("price_uzs"),
                    F("price_value"),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                ),
                route_km_anno=Coalesce(F("route_km_cached"), F("path_km")),
                company_rating=Avg("customer__ratings_received__score"),
            )
            .select_related("customer")
        )

        p = self.request.query_params

        # --- Базовые фильтры ---
        if p.get("uuid"):
            qs = qs.filter(uuid=p["uuid"])
        if p.get("origin_city"):
            qs = qs.filter(origin_city__iexact=p["origin_city"])
        if p.get("destination_city"):
            qs = qs.filter(destination_city__iexact=p["destination_city"])
        if p.get("load_date"):
            qs = qs.filter(load_date=p["load_date"])
        if p.get("load_date_from"):
            qs = qs.filter(load_date__gte=p["load_date_from"])
        if p.get("load_date_to"):
            qs = qs.filter(load_date__lte=p["load_date_to"])
        if p.get("transport_type"):
            qs = qs.filter(transport_type=p["transport_type"])

        # --- Вес ---
        if p.get("min_weight"):
            qs = qs.filter(weight_kg__gte=p["min_weight"])
        if p.get("max_weight"):
            qs = qs.filter(weight_kg__lte=p["max_weight"])

        # --- Новые фильтры: оси и объём ---
        if p.get("axles_min"):
            qs = qs.filter(axles__gte=p["axles_min"])
        if p.get("axles_max"):
            qs = qs.filter(axles__lte=p["axles_max"])
        if p.get("volume_min"):
            qs = qs.filter(volume_m3__gte=p["volume_min"])
        if p.get("volume_max"):
            qs = qs.filter(volume_m3__lte=p["volume_max"])

        # --- Цена (в суммах) ---
        if p.get("min_price_uzs"):
            qs = qs.filter(price_uzs_anno__gte=p["min_price_uzs"])
        if p.get("max_price_uzs"):
            qs = qs.filter(price_uzs_anno__lte=p["max_price_uzs"])

        # --- Радиусные фильтры ---
        o_lat, o_lng, o_r = p.get("origin_lat"), p.get("origin_lng"), p.get("origin_radius_km")
        if o_lat and o_lng and o_r:
            try:
                origin_point = Point(float(o_lng), float(o_lat), srid=4326)
                radius_km = float(o_r)
                qs = qs.filter(origin_point__distance_lte=(origin_point, D(km=radius_km)))
                qs = qs.annotate(
                    origin_dist_km=Distance("origin_point", origin_point) / 1000.0,
                    origin_radius_km=Value(radius_km, output_field=FloatField()),
                )
            except (TypeError, ValueError):
                pass

        d_lat, d_lng, d_r = p.get("dest_lat"), p.get("dest_lng"), p.get("dest_radius_km")
        if d_lat and d_lng and d_r:
            try:
                dest_point = Point(float(d_lng), float(d_lat), srid=4326)
                radius_km2 = float(d_r)
                qs = qs.filter(dest_point__distance_lte=(dest_point, D(km=radius_km2)))
                qs = qs.annotate(
                    dest_radius_km=Value(radius_km2, output_field=FloatField()),
                )
            except (TypeError, ValueError):
                pass

        # 🔎 Поиск по компании / аккаунту
        q = p.get("company") or p.get("q")
        if q:
            qs = qs.filter(
                Q(customer__company_name__icontains=q)
                | Q(customer__username__icontains=q)
                | Q(customer__email__icontains=q)
            )

        # 👤 Фильтры по контактам владельца
        if p.get("customer_id"):
            qs = qs.filter(customer_id=p["customer_id"])
        if p.get("customer_email"):
            qs = qs.filter(customer__email__iexact=p["customer_email"])
        if p.get("customer_phone"):
            qs = qs.filter(
                Q(customer__phone__icontains=p["customer_phone"])
                | Q(customer__phone_number__icontains=p["customer_phone"])
            )

        # --- Сортировка ---
        allowed = {
            "path_km",
            "-path_km",
            "route_km_anno",
            "-route_km_anno",
            "origin_dist_km",
            "-origin_dist_km",
            "price_uzs_anno",
            "-price_uzs_anno",
            "load_date",
            "-load_date",
            "axles",
            "-axles",
            "volume_m3",
            "-volume_m3",
            "age_minutes_anno",
            "-age_minutes_anno",
        }
        order_alias = {
            "route_km": "route_km_anno",
            "-route_km": "-route_km_anno",
            "age_minutes": "age_minutes_anno",
            "-age_minutes": "-age_minutes_anno",
        }
        order = p.get("order")
        ordexpr = order_alias.get(order, order)
        if ordexpr in allowed:
            qs = qs.order_by(ordexpr)
        else:
            qs = qs.order_by("-refreshed_at", "-created_at")

        return qs


# ------------------ Отмена груза ------------------
@extend_schema(tags=["loads"])
class CargoCancelView(generics.GenericAPIView):
    permission_classes = [IsAuthenticatedAndVerified]
    serializer_class = RefreshResponseSerializer
    queryset = Cargo.objects.all()

    def post(self, request, uuid: str):
        if _swagger(self):
            return Response({"detail": "schema"}, status=status.HTTP_200_OK)

        cargo = get_object_or_404(Cargo, uuid=uuid)
        user_id = request.user.id

        if user_id not in (cargo.customer_id, getattr(cargo, "assigned_carrier_id", None)):
            return Response({"detail": "Нет доступа"}, status=status.HTTP_403_FORBIDDEN)

        if cargo.status in (CargoStatus.DELIVERED, CargoStatus.COMPLETED, CargoStatus.CANCELLED):
            return Response({"detail": "Статус уже финальный"}, status=status.HTTP_400_BAD_REQUEST)

        cargo.status = CargoStatus.CANCELLED
        cargo.save(update_fields=["status"])

        cargo.offers.update(is_active=False)
        return Response({"detail": "Перевозка отменена"}, status=status.HTTP_200_OK)
