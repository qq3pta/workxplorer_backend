from decimal import Decimal
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError
from django.db.models import (
    Avg,
    Count,
    DecimalField,
    F,
    FloatField,
    Func,
    Q,
)
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import generics, status
from rest_framework import serializers as drf_serializers
from rest_framework.response import Response

from api.loads.models import LoadInvite
from api.offers.models import Offer

from ..accounts.permissions import (
    IsAuthenticatedAndVerified,
    IsCustomerOrCarrierOrLogistic,
    IsCustomerOrLogistic,
)
from .choices import ModerationStatus
from .models import Cargo, CargoStatus
from common.utils import convert_to_uzs
from common.filters import apply_common_search_filters
from .serializers import CargoListSerializer, CargoPublishSerializer

INVITE_BASE_URL = "https://logistic-omega-eight.vercel.app/dashboard/desk/invite"


def _swagger(view) -> bool:
    return getattr(view, "swagger_fake_view", False)


class RefreshResponseSerializer(drf_serializers.Serializer):
    detail = drf_serializers.CharField()


class ExtractMinutes(Func):
    template = "EXTRACT(EPOCH FROM (NOW() - %(expressions)s)) / 60.0"
    output_field = FloatField()


@extend_schema(tags=["loads"])
class PublishCargoView(generics.CreateAPIView):
    permission_classes = [IsAuthenticatedAndVerified, IsCustomerOrLogistic]
    serializer_class = CargoPublishSerializer
    queryset = Cargo.objects.all()

    def perform_create(self, serializer):
        user = self.request.user

        cargo = serializer.save(created_by=user if user.role == "logistic" else None)

        cargo.update_price_uzs()
        return cargo

    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        cargo = self.perform_create(s)
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


@extend_schema(tags=["loads"])
class CargoDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticatedAndVerified, IsCustomerOrLogistic]
    serializer_class = CargoPublishSerializer
    queryset = Cargo.objects.all()

    def get_queryset(self):
        if _swagger(self):
            return Cargo.objects.none()

        user = self.request.user
        if user.role == "customer":
            return Cargo.objects.filter(customer=user)

        return Cargo.objects.all()

    def get_object(self):
        uuid = self.kwargs.get("uuid")
        return get_object_or_404(self.get_queryset(), uuid=uuid)

    def perform_update(self, serializer):
        cargo = serializer.save()
        cargo.refreshed_at = timezone.now()
        cargo.update_price_uzs()
        cargo.save(update_fields=["refreshed_at", "price_uzs"])


@extend_schema(tags=["loads"], responses=RefreshResponseSerializer)
class CargoRefreshView(generics.GenericAPIView):
    permission_classes = [IsAuthenticatedAndVerified, IsCustomerOrLogistic]
    serializer_class = RefreshResponseSerializer

    def post(self, request, uuid: str):
        if _swagger(self):
            return Response({"detail": "schema"}, status=status.HTTP_200_OK)

        cargo = get_object_or_404(Cargo, uuid=uuid, customer=request.user)

        try:
            cargo.bump()
        except ValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        return Response({"detail": "Обновлено"}, status=status.HTTP_200_OK)


@extend_schema(tags=["loads"])
class MyCargosView(generics.ListAPIView):
    permission_classes = [IsAuthenticatedAndVerified, IsCustomerOrLogistic]
    serializer_class = CargoListSerializer

    def get_queryset(self):
        user = self.request.user

        if user.role == "customer":
            qs = Cargo.objects.filter(customer=user)
        elif user.role == "logistic":
            qs = Cargo.objects.filter(created_by=user)
        else:
            return Cargo.objects.none()

        qs = qs.annotate(
            path_m=Distance(F("origin_point"), F("dest_point")),
            offers_active=Count("offers", filter=Q(offers__is_active=True)),
        ).annotate(
            path_km=F("path_m") / 1000.0,
            route_km=Coalesce(F("route_km_cached"), F("path_km")),
            price_uzs_anno=Coalesce(
                F("price_uzs"),
                F("price_value"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )

        # ---- ФИЛЬТРЫ ----
        p = self.request.query_params

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

        if p.get("min_weight"):
            qs = qs.filter(weight_kg__gte=p["min_weight"])
        if p.get("max_weight"):
            qs = qs.filter(weight_kg__lte=p["max_weight"])

        if p.get("volume_min"):
            qs = qs.filter(volume_m3__gte=p["volume_min"])
        if p.get("volume_max"):
            qs = qs.filter(volume_m3__lte=p["volume_max"])

        if p.get("min_price_uzs"):
            qs = qs.filter(price_uzs_anno__gte=p["min_price_uzs"])
        if p.get("max_price_uzs"):
            qs = qs.filter(price_uzs_anno__lte=p["max_price_uzs"])

        # Гео фильтры
        # ORIGIN
        o_lat = p.get("origin_lat")
        o_lng = p.get("origin_lng")
        o_r = p.get("origin_radius_km")

        if o_r is not None and o_lat is not None and o_lng is not None:
            try:
                pnt = Point(float(o_lng), float(o_lat), srid=4326)
                qs = qs.annotate(origin_dist_m=Distance("origin_point", pnt)).filter(
                    origin_dist_m__lte=float(o_r) * 1000
                )
            except Exception as e:
                print("ORIGIN GEO FILTER ERROR:", e)

        # ======================
        # GEO FILTER — DESTINATION
        # ======================
        d_lat = p.get("dest_lat")
        d_lng = p.get("dest_lng")
        d_r = p.get("dest_radius_km")

        if d_lat and d_lng and d_r:
            try:
                pnt = Point(float(d_lng), float(d_lat), srid=4326)
                qs = qs.annotate(dest_dist_m=Distance("dest_point", pnt)).filter(
                    dest_dist_m__lte=float(d_r) * 1000
                )
            except Exception as e:
                print("DEST GEO FILTER ERROR:", e)

        # ======================
        # COMPANY / SEARCH
        # ======================
        q = p.get("company") or p.get("q")
        if q:
            qs = qs.filter(
                Q(customer__company_name__icontains=q)
                | Q(customer__username__icontains=q)
                | Q(customer__email__icontains=q)
            )

        # ---- СОРТИРОВКА ---
        allowed = {
            "path_km",
            "-path_km",
            "route_km",
            "-route_km",
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
            qs = qs.order_by(order)
        else:
            qs = qs.order_by("-refreshed_at", "-created_at")

        return qs


@extend_schema(tags=["loads"])
class MyCargosBoardView(generics.ListAPIView):
    permission_classes = [IsAuthenticatedAndVerified, IsCustomerOrLogistic]
    serializer_class = CargoListSerializer

    def get_queryset(self):
        user = self.request.user

        qs = Cargo.objects.filter(
            Q(customer=user) | Q(created_by=user),
            status=CargoStatus.POSTED,  # ← ВАЖНО
        )

        qs = qs.annotate(
            path_m=Distance(F("origin_point"), F("dest_point")),
        ).annotate(
            path_km=F("path_m") / 1000.0,
            route_km=Coalesce(F("route_km_cached"), F("path_km")),
            price_uzs_anno=Coalesce(
                F("price_uzs"),
                F("price_value"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )

        qs = apply_common_search_filters(qs, self.request.query_params)

        return qs.order_by("-refreshed_at", "-created_at")


@extend_schema(tags=["loads"])
class PublicLoadsView(generics.ListAPIView):
    permission_classes = [IsAuthenticatedAndVerified, IsCustomerOrCarrierOrLogistic]
    serializer_class = CargoListSerializer

    def get_queryset(self):
        qs = Cargo.objects.filter(
            moderation_status=ModerationStatus.APPROVED,
            is_hidden=False,
            status=CargoStatus.POSTED,
        )

        qs = qs.exclude(origin_point__isnull=True).exclude(dest_point__isnull=True)

        qs = (
            qs.annotate(
                offers_active=Count("offers", filter=Q(offers__is_active=True)),
                age_minutes_anno=ExtractMinutes(F("refreshed_at")),
                path_m=Distance(F("origin_point"), F("dest_point")),
            )
            .annotate(
                path_km=F("path_m") / 1000.0,
                route_km=Coalesce(F("route_km_cached"), F("path_km")),
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

        o_lat = p.get("origin_lat") or p.get("lat")
        o_lng = p.get("origin_lng") or p.get("lng")
        o_r = p.get("origin_radius_km")

        d_lat = p.get("dest_lat")
        d_lng = p.get("dest_lng")
        d_r = p.get("dest_radius_km")

        o_r = float(o_r) if o_r else None
        d_r = float(d_r) if d_r else None

        # Есть / нет предложений
        has_offers = p.get("has_offers")
        if has_offers is not None:
            has_offers = str(has_offers).lower()
            if has_offers in ("true", "1"):
                qs = qs.filter(offers_active__gt=0)
            elif has_offers in ("false", "0"):
                qs = qs.filter(offers_active=0)

        if p.get("uuid"):
            qs = qs.filter(uuid=p["uuid"])
        if p.get("origin_city") and not o_r:
            qs = qs.filter(origin_city__iexact=p["origin_city"])
        if p.get("destination_city") and not d_r:
            qs = qs.filter(destination_city__iexact=p["destination_city"])
        if p.get("load_date"):
            qs = qs.filter(load_date=p["load_date"])
        if p.get("load_date_from"):
            qs = qs.filter(load_date__gte=p["load_date_from"])
        if p.get("load_date_to"):
            qs = qs.filter(load_date__lte=p["load_date_to"])

        if p.get("transport_type"):
            qs = qs.filter(transport_type=p["transport_type"])
        min_weight = p.get("min_weight")
        max_weight = p.get("max_weight")

        try:
            if min_weight is not None:
                qs = qs.filter(weight_kg__gte=float(min_weight) * 1000)
            if max_weight is not None:
                qs = qs.filter(weight_kg__lte=float(max_weight) * 1000)
        except ValueError:
            pass
        if p.get("axles_min"):
            qs = qs.filter(axles__gte=p["axles_min"])
        if p.get("axles_max"):
            qs = qs.filter(axles__lte=p["axles_max"])
        if p.get("volume_min"):
            qs = qs.filter(volume_m3__gte=p["volume_min"])
        if p.get("volume_max"):
            qs = qs.filter(volume_m3__lte=p["volume_max"])
        min_price = p.get("min_price")
        max_price = p.get("max_price")
        currency = p.get("price_currency")

        if currency:
            try:
                if min_price not in (None, ""):
                    min_price_uzs = convert_to_uzs(Decimal(min_price), currency)
                    qs = qs.filter(price_uzs_anno__gte=min_price_uzs)

                if max_price not in (None, ""):
                    max_price_uzs = convert_to_uzs(Decimal(max_price), currency)
                    qs = qs.filter(price_uzs_anno__lte=max_price_uzs)
            except Exception as e:
                print("PRICE FILTER ERROR:", e)

        q = p.get("company") or p.get("q")
        if q:
            qs = qs.filter(
                Q(customer__company_name__icontains=q)
                | Q(customer__username__icontains=q)
                | Q(customer__email__icontains=q)
            )

        if p.get("customer_id"):
            qs = qs.filter(customer_id=p["customer_id"])
        if p.get("customer_email"):
            qs = qs.filter(customer__email__iexact=p["customer_email"])
        if p.get("customer_phone"):
            qs = qs.filter(
                Q(customer__phone__icontains=p["customer_phone"])
                | Q(customer__phone_number__icontains=p["customer_phone"])
            )
        # ---------- ORIGIN GEO FILTER (ОТКУДА + РАДИУС) ----------
        if o_lat and o_lng and o_r:
            try:
                origin_center = Point(float(o_lng), float(o_lat), srid=4326)

                qs = qs.annotate(
                    origin_dist_km=Distance("origin_point", origin_center) / 1000.0
                ).filter(origin_dist_km__lte=float(o_r))
            except Exception as e:
                print("ORIGIN GEO FILTER ERROR:", e)

        # ---------- DESTINATION GEO FILTER (КУДА + РАДИУС) ----------
        if d_r is not None and d_lat is not None and d_lng is not None:
            try:
                dest_center = Point(float(d_lng), float(d_lat), srid=4326)

                qs = qs.annotate(dest_dist_km=Distance("dest_point", dest_center) / 1000.0).filter(
                    dest_dist_km__lte=float(d_r)
                )
            except Exception as e:
                print("DEST GEO FILTER ERROR:", e)

        allowed = {
            "path_km",
            "-path_km",
            "route_km",
            "-route_km",
            "origin_dist_km",
            "-origin_dist_km",
            "dest_dist_km",
            "-dest_dist_km",
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
            "route_km": "route_km",
            "-route_km": "-route_km",
            "age_minutes": "age_minutes_anno",
            "-age_minutes": "-age_minutes_anno",
        }

        order = order_alias.get(p.get("order"), p.get("order"))

        if order in allowed:
            qs = qs.order_by(order)
        else:
            qs = qs.order_by("-refreshed_at", "-created_at")

        return qs


@extend_schema(tags=["loads"])
class CargoCancelView(generics.GenericAPIView):
    permission_classes = [IsAuthenticatedAndVerified]
    serializer_class = RefreshResponseSerializer

    def post(self, request, uuid: str):
        if _swagger(self):
            return Response({"detail": "schema"}, status=status.HTTP_200_OK)

        cargo = get_object_or_404(Cargo, uuid=uuid)
        user = request.user

        allowed_users = {
            cargo.customer_id,
            getattr(cargo, "assigned_carrier_id", None),
        }

        if user.id not in allowed_users:
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


@extend_schema(
    tags=["loads"],
    request=inline_serializer(
        name="CargoVisibilityRequest",
        fields={"is_hidden": drf_serializers.BooleanField()},
    ),
    responses={
        200: inline_serializer(
            name="CargoVisibilityResponse",
            fields={
                "detail": drf_serializers.CharField(),
                "is_hidden_for_me": drf_serializers.BooleanField(),
            },
        )
    },
)
@extend_schema(
    tags=["loads"],
    request=inline_serializer(
        name="CargoVisibilityRequest",
        fields={"is_hidden": drf_serializers.BooleanField()},
    ),
    responses={
        200: inline_serializer(
            name="CargoVisibilityResponse",
            fields={
                "detail": drf_serializers.CharField(),
                "is_hidden_for_me": drf_serializers.BooleanField(),
            },
        )
    },
)
class CargoVisibilityView(generics.GenericAPIView):
    permission_classes = [IsAuthenticatedAndVerified, IsCustomerOrLogistic]

    def post(self, request, uuid: str):
        cargo = get_object_or_404(Cargo, uuid=uuid)
        user = request.user

        # доступ — только автор
        if user.role == "customer" and cargo.customer_id != user.id:
            return Response({"detail": "Нет доступа"}, status=403)

        if user.role == "logistic" and cargo.created_by_id != user.id:
            return Response({"detail": "Нет доступа"}, status=403)

        is_hidden = request.data.get("is_hidden")
        if not isinstance(is_hidden, bool):
            return Response({"detail": "is_hidden must be boolean"}, status=400)

        cargo.is_hidden = is_hidden
        cargo.save(update_fields=["is_hidden"])

        return Response(
            {
                "detail": "Видимость обновлена",
                "is_hidden": cargo.is_hidden,
            },
            status=200,
        )


@extend_schema(
    tags=["loads"],
    responses={
        200: inline_serializer(
            name="GenerateInviteResponse",
            fields={
                "token": drf_serializers.CharField(),
                "invite_url": drf_serializers.CharField(),
            },
        )
    },
)
class CargoInviteGenerateView(generics.GenericAPIView):
    permission_classes = [IsAuthenticatedAndVerified, IsCustomerOrLogistic]

    def post(self, request, uuid: str):
        """
        Создание токен-ссылки на груз.
        Генерируют customer или logistic.
        """
        cargo = get_object_or_404(Cargo, uuid=uuid)

        if cargo.customer_id != request.user.id and request.user.role != "logistic":
            return Response({"detail": "Нет доступа"}, status=403)

        token = LoadInvite.generate_token()

        LoadInvite.objects.create(
            load=cargo,
            token=token,
            created_by=request.user,
        )

        invite_url = f"{INVITE_BASE_URL}/{token}"

        return Response(
            {
                "token": token,
                "invite_url": invite_url,
            },
            status=200,
        )


@extend_schema(
    tags=["loads"],
    responses={
        200: inline_serializer(
            name="OpenInviteResponse",
            fields={
                "cargo_id": drf_serializers.IntegerField(),
                "carrier_id": drf_serializers.IntegerField(),
                "invited_by_id": drf_serializers.IntegerField(),
                "cargo": CargoListSerializer(),
                "expires_at": drf_serializers.DateTimeField(),
            },
        )
    },
)
class CargoInviteOpenView(generics.GenericAPIView):
    permission_classes = [IsAuthenticatedAndVerified]

    def get(self, request, token: str):
        invite = get_object_or_404(LoadInvite, token=token)

        if invite.expires_at < timezone.now():
            return Response({"detail": "Ссылка истекла"}, status=400)

        cargo = (
            Cargo.objects.filter(id=invite.load_id)
            .annotate(
                path_m=Distance(F("origin_point"), F("dest_point")),
            )
            .annotate(
                path_km=F("path_m") / 1000.0,
                route_km=Coalesce(F("route_km_cached"), F("path_km")),
                price_uzs_anno=Coalesce(
                    F("price_uzs"),
                    F("price_value"),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                ),
                company_rating=Avg("customer__ratings_received__score"),
            )
            .select_related("customer")
            .first()
        )

        carrier = request.user
        invited_by = invite.created_by

        offer, created = Offer.objects.get_or_create(
            cargo_id=cargo.id,
            carrier_id=carrier.id,
            defaults={
                "initiator": Offer.Initiator.CUSTOMER,
                "price_value": cargo.price_value or 0,
            },
        )

        return Response(
            {
                "cargo_id": cargo.id,
                "carrier_id": carrier.id,
                "invited_by_id": invited_by.id if invited_by else None,
                "offer_id": offer.id,
                "expires_at": invite.expires_at,
                "cargo": CargoListSerializer(cargo, context={"request": request}).data,
            }
        )
