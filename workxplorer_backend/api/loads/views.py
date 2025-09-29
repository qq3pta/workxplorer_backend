from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.core.exceptions import ValidationError
from django.db.models import Count, F, FloatField, Q
from django.db.models.expressions import Func
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework import serializers as drf_serializers
from rest_framework.response import Response

from ..accounts.permissions import IsAuthenticatedAndVerified, IsCarrier, IsCustomer
from .choices import ModerationStatus
from .models import Cargo, CargoStatus
from .serializers import CargoListSerializer, CargoPublishSerializer


def _swagger(view) -> bool:
    """True, когда drf-spectacular генерирует схему и у вьюхи нет реального request.user."""
    return getattr(view, "swagger_fake_view", False)


class RefreshResponseSerializer(drf_serializers.Serializer):
    """Простой сериализатор для ответа refresh."""

    detail = drf_serializers.CharField()


class DistanceGeography(Func):
    """
    ST_Distance(a::geography, b::geography) -> расстояние в метрах по сфере Земли.
    """

    output_field = FloatField()
    function = "ST_Distance"

    def as_sql(self, compiler, connection, **extra_context):
        lhs, lhs_params = compiler.compile(self.source_expressions[0])
        rhs, rhs_params = compiler.compile(self.source_expressions[1])
        sql = f"ST_Distance({lhs}::geography, {rhs}::geography)"
        return sql, lhs_params + rhs_params


@extend_schema(tags=["loads"])
class PublishCargoView(generics.CreateAPIView):
    permission_classes = [IsAuthenticatedAndVerified, IsCustomer]
    serializer_class = CargoPublishSerializer
    queryset = Cargo.objects.all()

    def create(self, request, *args, **kwargs):
        """
        Создаём груз, геокодим точки, сразу считаем маршрут по трассе (через сериалайзер)
        и возвращаем километраж в ответе.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cargo = serializer.save()  # внутри create() уже вызывается update_route_cache(save=True)
        # пересериализуем созданный объект, чтобы получить route_kм из миксина
        data = self.get_serializer(cargo).data
        payload = {
            "message": "Заявка успешно опубликована и отправлена на модерацию",
            "id": cargo.id,
            "route_km": data.get("route_km"),
        }
        return Response(
            payload, status=status.HTTP_201_CREATED, headers=self.get_success_headers(data)
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
        obj = serializer.save()  # сериалайзер сам пересчитает route_km при смене точек
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
    """
    - select_related('customer') для company_name/contact_value
    - annotate offers_active для has_offers без N+1
    - annotate path_km для расчёта price_per_km (фолбэк)
    """

    permission_classes = [IsAuthenticatedAndVerified, IsCustomer]
    serializer_class = CargoListSerializer
    queryset = Cargo.objects.all()

    def get_queryset(self):
        if _swagger(self):
            return Cargo.objects.none()

        qs = Cargo.objects.filter(customer=self.request.user).annotate(
            offers_active=Count("offers", filter=Q(offers__is_active=True))
        )

        qs = qs.annotate(path_m=DistanceGeography(F("origin_point"), F("dest_point")))
        qs = qs.annotate(path_km=F("path_m") / 1000.0)

        return qs.select_related("customer").order_by("-refreshed_at", "-created_at")


@extend_schema(tags=["loads"])
class MyCargosBoardView(generics.ListAPIView):
    """
    Борда моих активных заявок.
    - select_related('customer')
    - offers_active для has_offers
    - path_km для price_per_km (фолбэк)
    """

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

        qs = qs.annotate(offers_active=Count("offers", filter=Q(offers__is_active=True)))
        qs = qs.annotate(path_m=DistanceGeography(F("origin_point"), F("dest_point")))
        qs = qs.annotate(path_km=F("path_m") / 1000.0)

        return qs.select_related("customer").order_by("-refreshed_at", "-created_at")


@extend_schema(tags=["loads"])
class PublicLoadsView(generics.ListAPIView):
    """
    Публичная доска: видна Перевозчику/Логисту.
    Показывает только одобренные, не скрытые и активные заявки.

    Поддерживаемые query params:
    - origin_city, destination_city, load_date, transport_type, id
    - min_weight, max_weight, min_price, max_price, price_currency
    - has_offers = true|false
    - origin_lat, origin_lng, origin_radius_km
    - dest_lat,   dest_lng,   dest_radius_km
    - order = path_km|-path_km|origin_dist_km|-origin_dist_km|price_value|-price_value|load_date|-load_date
    """

    permission_classes = [IsAuthenticatedAndVerified, IsCarrier]
    serializer_class = CargoListSerializer
    queryset = Cargo.objects.all()

    def get_queryset(self):
        qs = Cargo.objects.filter(
            is_hidden=False,
            moderation_status=ModerationStatus.APPROVED,
            status=CargoStatus.POSTED,
        ).annotate(offers_active=Count("offers", filter=Q(offers__is_active=True)))

        p = self.request.query_params

        # Город/дата/тип/id
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

        # Вес
        if p.get("min_weight"):
            qs = qs.filter(weight_kg__gte=p["min_weight"])
        if p.get("max_weight"):
            qs = qs.filter(weight_kg__lte=p["max_weight"])

        # Цена и валюта (без конвертации)
        if p.get("min_price"):
            qs = qs.filter(price_value__gte=p["min_price"])
        if p.get("max_price"):
            qs = qs.filter(price_value__lte=p["max_price"])
        price_currency = p.get("price_currency")
        if price_currency and any(f.name == "price_currency" for f in Cargo._meta.get_fields()):
            qs = qs.filter(price_currency=price_currency)

        # Наличие активных предложений
        has_offers = p.get("has_offers")
        if has_offers in {"true", "1"}:
            qs = qs.filter(offers_active__gt=0)
        elif has_offers in {"false", "0"}:
            qs = qs.filter(offers_active=0)

        # --- Радиусные фильтры (PostGIS) ---
        o_lat = p.get("origin_lat")
        o_lng = p.get("origin_lng")
        o_r = p.get("origin_radius_km")
        origin_point_for_order = None
        if o_lat and o_lng and o_r:
            origin_point_for_order = Point(float(o_lng), float(o_lat), srid=4326)
            qs = qs.filter(origin_point__distance_lte=(origin_point_for_order, D(km=float(o_r))))
            # аннотируем расстояние до origin в км (метры -> км)
            qs = qs.annotate(
                origin_dist_km=Distance("origin_point", origin_point_for_order) / 1000.0
            )

        d_lat = p.get("dest_lat")
        d_lng = p.get("dest_lng")
        d_r = p.get("dest_radius_km")
        if d_lat and d_lng and d_r:
            dest_point_for_filter = Point(float(d_lng), float(d_lat), srid=4326)
            qs = qs.filter(dest_point__distance_lte=(dest_point_for_filter, D(km=float(d_r))))

        # Путь между городами (метры -> км) для price_per_km (фолбэк)
        qs = qs.annotate(path_m=DistanceGeography(F("origin_point"), F("dest_point")))
        qs = qs.annotate(path_km=F("path_m") / 1000.0)

        order = p.get("order")
        allowed = {
            "path_km",
            "-path_km",
            "origin_dist_km",
            "-origin_dist_km",
            "price_value",
            "-price_value",
            "load_date",
            "-load_date",
        }
        if order in allowed:
            qs = qs.order_by(order)
        else:
            if origin_point_for_order is not None:
                qs = qs.order_by("origin_dist_km", "-refreshed_at", "-created_at")
            else:
                qs = qs.order_by("-refreshed_at", "-created_at")

        return qs.select_related("customer")


@extend_schema(tags=["loads"])
class CargoCancelView(generics.GenericAPIView):
    """
    Отмена активной перевозки:
    - право: автор груза ИЛИ назначенный перевозчик
    - доступна только для статусов: POSTED, MATCHED
    - ставит статус CANCELLED и деактивирует офферы
    """

    permission_classes = [IsAuthenticatedAndVerified]
    serializer_class = RefreshResponseSerializer  # простой ответ
    queryset = Cargo.objects.all()

    def post(self, request, pk: int):
        if _swagger(self):
            return Response({"detail": "schema"}, status=status.HTTP_200_OK)

        cargo = get_object_or_404(Cargo, pk=pk)

        user_id = request.user.id
        if user_id not in (cargo.customer_id, getattr(cargo, "assigned_carrier_id", None)):
            return Response({"detail": "Нет доступа"}, status=status.HTTP_403_FORBIDDEN)

        if cargo.status in (CargoStatus.DELIVERED, CargoStatus.COMPLETED, CargoStatus.CANCELLED):
            return Response({"detail": "Статус уже финальный"}, status=status.HTTP_400_BAD_REQUEST)

        cargo.status = CargoStatus.CANCELLED
        cargo.save(update_fields=["status"])
        cargo.offers.update(is_active=False)
        return Response({"detail": "Перевозка отменена"}, status=status.HTTP_200_OK)
