from django.contrib.gis.db.models.functions import Distance
from common.filters import apply_loads_filters
from django.core.exceptions import ValidationError
from django.db.models import (
    Avg,
    Count,
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
            offers_active=Count("offers", filter=Q(offers__is_active=True)),
            path_m=Distance(F("origin_point"), F("dest_point")),
        ).annotate(
            path_km=F("path_m") / 1000.0,
            route_km=Coalesce(F("route_km_cached"), F("path_km")),
            price_uzs_anno=F("price_uzs"),
        )

        return apply_loads_filters(qs, self.request.query_params)


class MyCargosBoardView(generics.ListAPIView):
    permission_classes = [IsAuthenticatedAndVerified, IsCustomerOrLogistic]
    serializer_class = CargoListSerializer

    def get_queryset(self):
        user = self.request.user

        qs = (
            Cargo.objects.filter(
                Q(customer=user) | Q(created_by=user),
                status=CargoStatus.POSTED,
            )
            .annotate(
                offers_active=Count("offers", filter=Q(offers__is_active=True)),
                path_m=Distance(F("origin_point"), F("dest_point")),
            )
            .annotate(
                path_km=F("path_m") / 1000.0,
                route_km=Coalesce(F("route_km_cached"), F("path_km")),
                price_uzs_anno=F("price_uzs"),
            )
        )

        return apply_loads_filters(qs, self.request.query_params)


class PublicLoadsView(generics.ListAPIView):
    permission_classes = [IsAuthenticatedAndVerified, IsCustomerOrCarrierOrLogistic]
    serializer_class = CargoListSerializer

    def get_queryset(self):
        qs = (
            Cargo.objects.filter(
                moderation_status=ModerationStatus.APPROVED,
                is_hidden=False,
                status=CargoStatus.POSTED,
            )
            .exclude(
                origin_point__isnull=True,
                dest_point__isnull=True,
            )
            .annotate(
                offers_active=Count("offers", filter=Q(offers__is_active=True)),
                age_minutes_anno=ExtractMinutes(F("refreshed_at")),
                path_m=Distance(F("origin_point"), F("dest_point")),
            )
            .annotate(
                path_km=F("path_m") / 1000.0,
                route_km=Coalesce(F("route_km_cached"), F("path_km")),
                price_uzs_anno=F("price_uzs"),
                company_rating=Avg("customer__ratings_received__score"),
            )
            .select_related("customer")
        )

        return apply_loads_filters(qs, self.request.query_params)


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
                price_uzs_anno=F("price_uzs"),
                company_rating=Avg("customer__ratings_received__score"),
            )
            .select_related("customer")
            .first()
        )

        carrier = request.user
        invited_by = invite.created_by

        offer = Offer.objects.filter(
            cargo_id=cargo.id,
            carrier_id=carrier.id,
            is_active=True,
        ).first()

        if not offer:
            offer = Offer.objects.create(
                cargo=cargo,
                carrier=carrier,
                initiator=Offer.Initiator.CUSTOMER,
                deal_type=Offer.resolve_deal_type(
                    initiator_user=invite.created_by or cargo.customer,
                    carrier=carrier,
                ),
                price_value=cargo.price_value or 0,
                price_currency=cargo.price_currency,
                payment_method=Offer.PaymentMethod.CASH,
                message="",
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
