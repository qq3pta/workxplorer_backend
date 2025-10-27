from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from ..accounts.permissions import IsAuthenticatedAndVerified, IsCarrier, IsCustomer
from .models import Offer
from .serializers import (
    OfferAcceptResponseSerializer,
    OfferCounterSerializer,
    OfferCreateSerializer,
    OfferDetailSerializer,
    OfferInviteSerializer,
    OfferRejectResponseSerializer,
    OfferShortSerializer,
)


class EmptySerializer(serializers.Serializer):
    """Пустое тело запроса (для POST без body)."""

    pass


@extend_schema_view(
    list=extend_schema(
        tags=["offers"],
        summary="Список офферов (видимые текущему пользователю)",
        description=(
            "Возвращает офферы, доступные текущему пользователю. "
            "Можно уточнить выборку параметром `scope`.\n\n"
            "**scope=mine** — как Перевозчик (carrier);\n"
            "**scope=incoming** — входящие: для Заказчика/Логиста — офферы от перевозчиков; "
            "для Перевозчика — инвайты от заказчиков (initiator=CUSTOMER);\n"
            "**scope=all** — все (только для staff)."
        ),
        parameters=[
            OpenApiParameter(
                name="scope",
                description="mine | incoming | all (только staff)",
                required=False,
                type=str,
            ),
        ],
        responses=OfferShortSerializer(many=True),
    ),
    retrieve=extend_schema(
        tags=["offers"],
        summary="Детали оффера",
        description="Доступно перевозчику-автору, владельцу груза или логиcту.",
        responses=OfferDetailSerializer,
    ),
    create=extend_schema(
        tags=["offers"],
        summary="Создать оффер",
        description="Доступно только Перевозчику/Логисту.",
        request=OfferCreateSerializer,
        responses=OfferDetailSerializer,
    ),
)
@extend_schema(tags=["offers"])
class OfferViewSet(ModelViewSet):
    """
    Эндпоинты:
      POST   /api/offers/                  — создать (Перевозчик/Логист)
      GET    /api/offers/                  — список, видимый текущему пользователю (scope=…)
      GET    /api/offers/my/               — мои офферы как Перевозчик (alias)
      GET    /api/offers/incoming/         — входящие (alias): заказчик/логист — офферы от перевозчиков; перевозчик — инвайты
      GET    /api/offers/{id}/             — детали
      POST   /api/offers/{id}/accept/      — принять
      POST   /api/offers/{id}/reject/      — отклонить
      POST   /api/offers/{id}/counter/     — контр-предложение
      POST   /api/offers/invite/           — инвайт (Заказчик → Перевозчик)
    """

    queryset = Offer.objects.select_related("cargo", "carrier")
    permission_classes = [IsAuthenticatedAndVerified]
    serializer_class = OfferDetailSerializer

    def get_serializer_class(self):
        return {
            "list": OfferShortSerializer,
            "create": OfferCreateSerializer,
            "my": OfferShortSerializer,
            "incoming": OfferShortSerializer,
            "counter": OfferCounterSerializer,
            "accept": EmptySerializer,
            "reject": EmptySerializer,
            "invite": OfferInviteSerializer,  # NEW
        }.get(self.action, OfferDetailSerializer)

    # Права по action
    def get_permissions(self):
        if self.action in {"create", "my"}:
            classes = [IsAuthenticatedAndVerified, IsCarrier]
        elif self.action == "incoming":
            # входящие теперь доступны и Перевозчику (для инвайтов), и Заказчику/Логисту
            classes = [IsAuthenticatedAndVerified]
        elif self.action == "invite":
            classes = [IsAuthenticatedAndVerified, IsCustomer]
        else:
            classes = [IsAuthenticatedAndVerified]
        return [cls() for cls in classes]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Offer.objects.none()
        return super().get_queryset()

    def list(self, request, *args, **kwargs):
        u = request.user
        scope = request.query_params.get("scope")
        qs = self.get_queryset().filter(is_active=True)

        if scope == "mine":
            qs = qs.filter(carrier=u)
        elif scope == "incoming":
            # Заказчик/Логист видят входящие офферы от перевозчиков,
            # Перевозчик — инвайты от заказчика (initiator=CUSTOMER)
            if getattr(u, "is_carrier", False) or getattr(u, "role", None) == "CARRIER":
                qs = qs.filter(carrier=u, initiator=Offer.Initiator.CUSTOMER)
            else:
                qs = qs.filter(cargo__customer=u)
        elif scope == "all":
            if not getattr(u, "is_staff", False):
                return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)
            # staff видит все активные
        else:
            # умолчания по ролям
            if getattr(u, "is_carrier", False) or getattr(u, "role", None) == "CARRIER":
                qs = qs.filter(carrier=u)
            elif getattr(u, "is_customer", False) or getattr(u, "role", None) == "CUSTOMER":
                qs = qs.filter(cargo__customer=u)
            elif getattr(u, "is_logistic", False):
                qs = qs.filter(Q(cargo__customer=u) | Q(carrier=u))
            else:
                qs = qs.none()

        qs = qs.order_by("-created_at")
        page = self.paginate_queryset(qs)
        ser = OfferShortSerializer(page or qs, many=True)
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)

    @extend_schema(
        tags=["offers"],
        summary="Мои офферы (Перевозчик)",
        description="Alias к `GET /api/offers/?scope=mine`.",
        responses=OfferShortSerializer(many=True),
    )
    @action(detail=False, methods=["get"])
    def my(self, request):
        qs = self.get_queryset().filter(carrier=request.user).order_by("-created_at")
        page = self.paginate_queryset(qs)
        ser = self.get_serializer(page or qs, many=True)
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)

    @extend_schema(
        tags=["offers"],
        summary="Входящие офферы / инвайты",
        description=(
            "Alias к `GET /api/offers/?scope=incoming`.\n"
            "Заказчик/Логист — видят офферы от перевозчиков на их заявки.\n"
            "Перевозчик — видит инвайты от заказчиков (initiator=CUSTOMER)."
        ),
        responses=OfferShortSerializer(many=True),
    )
    @action(detail=False, methods=["get"])
    def incoming(self, request):
        u = request.user
        if getattr(u, "is_carrier", False) or getattr(u, "role", None) == "CARRIER":
            qs = self.get_queryset().filter(
                carrier=u, is_active=True, initiator=Offer.Initiator.CUSTOMER
            )
        else:
            qs = self.get_queryset().filter(cargo__customer=u, is_active=True)
        qs = qs.order_by("-created_at")
        page = self.paginate_queryset(qs)
        ser = self.get_serializer(page or qs, many=True)
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)

    @extend_schema(responses=OfferDetailSerializer)
    def retrieve(self, request, *args, **kwargs):
        obj = self.get_object()
        u = request.user
        if u.id not in (obj.carrier_id, obj.cargo.customer_id) and not getattr(
            u, "is_logistic", False
        ):
            raise PermissionDenied("Нет доступа к офферу")
        return Response(self.get_serializer(obj).data)

    # --------- действия ---------
    @extend_schema(
        tags=["offers"],
        summary="Принять оффер",
        description="Акцепт оффера текущим пользователем. При взаимном акцепте создаётся Shipment.",
        request=None,
        responses={
            200: OfferAcceptResponseSerializer,
            403: OpenApiResponse(description="Forbidden"),
            404: OpenApiResponse(description="Not Found"),
        },
    )
    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        offer = self.get_object()
        try:
            offer.accept_by(request.user)
        except PermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
        return Response(
            {
                "detail": "Принято",
                "accepted_by_customer": offer.accepted_by_customer,
                "accepted_by_carrier": offer.accepted_by_carrier,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["offers"],
        summary="Отклонить оффер",
        description="Отклонение/снятие оффера любой из сторон. Делает оффер неактивным.",
        request=None,
        responses={
            200: OfferRejectResponseSerializer,
            403: OpenApiResponse(description="Forbidden"),
            404: OpenApiResponse(description="Not Found"),
        },
    )
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        offer = self.get_object()
        try:
            offer.reject_by(request.user)
        except PermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)
        return Response({"detail": "Отклонено"}, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["offers"],
        summary="Контр-предложение",
        description="Создать контр-предложение. Разрешено владельцу груза или перевозчику этого оффера.",
        request=OfferCounterSerializer,
        responses=OfferDetailSerializer,
    )
    @action(detail=True, methods=["post"])
    def counter(self, request, pk=None):
        offer = self.get_object()
        u = request.user
        if u.id not in (offer.cargo.customer_id, offer.carrier_id) and not getattr(
            u, "is_staff", False
        ):
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)

        with transaction.atomic():
            offer.make_counter(
                price_value=ser.validated_data["price_value"],
                price_currency=ser.validated_data.get("price_currency"),
                message=ser.validated_data.get("message"),
            )

        return Response(OfferDetailSerializer(offer).data, status=status.HTTP_200_OK)

    # --------- инвайт ---------
    @extend_schema(
        tags=["offers"],
        summary="Инвайт перевозчику (Заказчик)",
        description="Заказчик отправляет персональное предложение перевозчику на свой груз.",
        request=OfferInviteSerializer,
        responses=OfferDetailSerializer,
    )
    @action(detail=False, methods=["post"])
    def invite(self, request):
        # Права уже проверяются в get_permissions: IsAuthenticatedAndVerified + IsCustomer
        ser = self.get_serializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        with transaction.atomic():
            offer = ser.save()
        return Response(OfferDetailSerializer(offer).data, status=status.HTTP_201_CREATED)
