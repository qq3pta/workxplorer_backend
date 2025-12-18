from django.contrib.gis.db.models.functions import Distance
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Avg, F, FloatField, Q

from django.db.models.functions import Coalesce
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
from .permissions import IsOfferParticipant

from api.orders.models import Order

from ..accounts.permissions import (
    IsAuthenticatedAndVerified,
    IsCustomerOrCarrierOrLogistic,
)
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


def _apply_common_filters(qs, params):
    """
    Общие фильтры/поиск для list/my/incoming:
      - cargo / carrier / customer filters
      - инициатор, активность, акцепты
      - даты (created, load/delivery)
      - поиск по компании/почте/телефону
      - сортировка
    """
    p = params

    if p.get("cargo_id"):
        qs = qs.filter(cargo_id=p["cargo_id"])
    if p.get("cargo_uuid"):
        qs = qs.filter(cargo__uuid=p["cargo_uuid"])
    if p.get("carrier_id"):
        qs = qs.filter(carrier_id=p["carrier_id"])
    if p.get("customer_id"):
        qs = qs.filter(cargo__customer_id=p["customer_id"])

    if p.get("initiator"):
        qs = qs.filter(initiator=p["initiator"])
    if p.get("is_active") in ("true", "false", "1", "0"):
        qs = qs.filter(is_active=p.get("is_active") in ("true", "1"))
    if p.get("accepted_by_customer") in ("true", "false", "1", "0"):
        qs = qs.filter(accepted_by_customer=p.get("accepted_by_customer") in ("true", "1"))
    if p.get("accepted_by_carrier") in ("true", "false", "1", "0"):
        qs = qs.filter(accepted_by_carrier=p.get("accepted_by_carrier") in ("true", "1"))

    if p.get("created_from"):
        qs = qs.filter(created_at__gte=p["created_from"])
    if p.get("created_to"):
        qs = qs.filter(created_at__lte=p["created_to"])

    if p.get("load_date_from"):
        qs = qs.filter(cargo__load_date__gte=p["load_date_from"])
    if p.get("load_date_to"):
        qs = qs.filter(cargo__load_date__lte=p["load_date_to"])
    if p.get("delivery_date_from"):
        qs = qs.filter(cargo__delivery_date__gte=p["delivery_date_from"])
    if p.get("delivery_date_to"):
        qs = qs.filter(cargo__delivery_date__lte=p["delivery_date_to"])

    if p.get("origin_city"):
        qs = qs.filter(cargo__origin_city__iexact=p["origin_city"])
    if p.get("destination_city"):
        qs = qs.filter(cargo__destination_city__iexact=p["destination_city"])

    q = p.get("company") or p.get("q")
    if q:
        qs = qs.filter(
            Q(cargo__customer__company_name__icontains=q)
            | Q(cargo__customer__username__icontains=q)
            | Q(cargo__customer__email__icontains=q)
            | Q(carrier__company_name__icontains=q)
            | Q(carrier__username__icontains=q)
            | Q(carrier__email__icontains=q)
        )

    if p.get("customer_email"):
        qs = qs.filter(cargo__customer__email__iexact=p["customer_email"])
    if p.get("customer_phone"):
        qs = qs.filter(
            Q(cargo__customer__phone__icontains=p["customer_phone"])
            | Q(cargo__customer__phone_number__icontains=p["customer_phone"])
        )
    if p.get("carrier_email"):
        qs = qs.filter(carrier__email__iexact=p["carrier_email"])
    if p.get("carrier_phone"):
        qs = qs.filter(
            Q(carrier__phone__icontains=p["carrier_phone"])
            | Q(carrier__phone_number__icontains=p["carrier_phone"])
        )

    allowed = {
        "created_at",
        "-created_at",
        "price_value",
        "-price_value",
        "cargo__load_date",
        "-cargo__load_date",
        "cargo__delivery_date",
        "-cargo__delivery_date",
        "carrier_rating",
        "-carrier_rating",
    }
    order = p.get("order")
    if order in allowed:
        qs = qs.order_by(order)
    else:
        qs = qs.order_by("-created_at")

    return qs


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
            "**scope=all** — все (только для staff).\n\n"
            "Доп. query: cargo_id, cargo_uuid, carrier_id, customer_id, initiator, "
            "is_active, accepted_by_customer, accepted_by_carrier, "
            "created_from/to, load_date_from/to, delivery_date_from/to, "
            "origin_city, destination_city, company|q, customer_email/phone, "
            "carrier_email/phone, order (в т.ч. carrier_rating / -carrier_rating)"
        ),
        parameters=[
            OpenApiParameter(
                "scope", required=False, type=str, description="mine | incoming | all"
            ),
            OpenApiParameter("cargo_id", required=False, type=str),
            OpenApiParameter("cargo_uuid", required=False, type=str),
            OpenApiParameter("carrier_id", required=False, type=str),
            OpenApiParameter("customer_id", required=False, type=str),
            OpenApiParameter(
                "initiator", required=False, type=str, description="CUSTOMER | CARRIER"
            ),
            OpenApiParameter("is_active", required=False, type=str, description="true|false"),
            OpenApiParameter(
                "accepted_by_customer", required=False, type=str, description="true|false"
            ),
            OpenApiParameter(
                "accepted_by_carrier", required=False, type=str, description="true|false"
            ),
            OpenApiParameter("created_from", required=False, type=str),
            OpenApiParameter("created_to", required=False, type=str),
            OpenApiParameter("load_date_from", required=False, type=str),
            OpenApiParameter("load_date_to", required=False, type=str),
            OpenApiParameter("delivery_date_from", required=False, type=str),
            OpenApiParameter("delivery_date_to", required=False, type=str),
            OpenApiParameter("origin_city", required=False, type=str),
            OpenApiParameter("destination_city", required=False, type=str),
            OpenApiParameter("company", required=False, type=str, description="или q"),
            OpenApiParameter("q", required=False, type=str),
            OpenApiParameter("customer_email", required=False, type=str),
            OpenApiParameter("customer_phone", required=False, type=str),
            OpenApiParameter("carrier_email", required=False, type=str),
            OpenApiParameter("carrier_phone", required=False, type=str),
            OpenApiParameter("order", required=False, type=str),
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
        description="Доступно только Перевозчику.",
        request=OfferCreateSerializer,
        responses=OfferDetailSerializer,
    ),
)
@extend_schema(tags=["offers"])
class OfferViewSet(ModelViewSet):
    """
    Эндпоинты:
      POST   /api/offers/                  — создать (Перевозчик)
      GET    /api/offers/                  — список, видимый текущему пользователю (scope=…)
      GET    /api/offers/my/               — мои офферы как Перевозчик (alias)
      GET    /api/offers/incoming/         — входящие (alias): заказчик/логист — офферы от перевозчиков; перевозчик — инвайты
      GET    /api/offers/{id}/             — детали
      POST   /api/offers/{id}/accept/      — принять
      POST   /api/offers/{id}/reject/      — отклонить
      POST   /api/offers/{id}/counter/     — контр-предложение
      POST   /api/offers/invite/           — инвайт (Заказчик → Перевозчик)
    """

    queryset = (
        Offer.objects.select_related("cargo", "carrier")
        .annotate(
            carrier_rating=Avg("carrier__ratings_received__score"),
            # 1. Сначала вычисляем дистанцию по прямой (path_km) для fallback
            path_m_anno=Distance(
                F("cargo__origin_point"),
                F("cargo__dest_point"),
            ),
        )
        .annotate(
            path_km_anno=F("path_m_anno") / 1000.0,
            # 2. Вычисляем окончательное расстояние route_km:
            # Приоритет: cargo__route_km_cached, иначе path_km_anno
            route_km=Coalesce(
                F("cargo__route_km_cached"), F("path_km_anno"), output_field=FloatField()
            ),
        )
    )
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
            "invite": OfferInviteSerializer,
        }.get(self.action, OfferDetailSerializer)

    def get_permissions(self):
        if self.action == "create":
            classes = [IsAuthenticatedAndVerified, IsCustomerOrCarrierOrLogistic]

        elif self.action in {"accept", "reject", "counter", "retrieve"}:
            classes = [
                IsAuthenticatedAndVerified,
                IsOfferParticipant,
            ]

        elif self.action == "invite":
            classes = [IsAuthenticatedAndVerified, IsCustomerOrCarrierOrLogistic]

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
        qs = self.get_queryset()

        if scope == "mine":
            qs = qs.filter(carrier=u)
        elif scope == "incoming":
            if getattr(u, "is_carrier", False) or getattr(u, "role", None) == "CARRIER":
                qs = qs.filter(carrier=u, initiator=Offer.Initiator.CUSTOMER)
            else:
                qs = qs.filter(cargo__customer=u)
        elif scope == "all":
            if not getattr(u, "is_staff", False):
                return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)
        else:
            if getattr(u, "is_carrier", False) or getattr(u, "role", None) == "CARRIER":
                qs = qs.filter(carrier=u)
            elif getattr(u, "is_customer", False) or getattr(u, "role", None) == "CUSTOMER":
                qs = qs.filter(cargo__customer=u)
            elif getattr(u, "is_logistic", False):
                qs = qs.filter(
                    Q(cargo__customer=u)
                    | Q(cargo__created_by=u)
                    | Q(logistic=u)
                    | Q(intermediary=u)
                ).distinct()
            else:
                qs = qs.none()

        qs = _apply_common_filters(qs, request.query_params)

        # ------------------ Фильтр по response_status ------------------
        response_status = request.query_params.get("response_status")
        if response_status:
            qs = [o for o in qs if o.get_response_status_for(u) == response_status]
        # ----------------------------------------------------------------

        page = self.paginate_queryset(qs)
        ser = OfferShortSerializer(page or qs, many=True, context={"request": request})
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)

    @extend_schema(
        tags=["offers"],
        summary="Мои офферы (Перевозчик)",
        description="Alias к `GET /api/offers/?scope=mine`.",
        responses=OfferShortSerializer(many=True),
    )
    @action(detail=False, methods=["get"])
    def my(self, request):
        qs = self.get_queryset().filter(carrier=request.user)
        qs = _apply_common_filters(qs, request.query_params)
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
        qs = self.get_queryset()

        if getattr(u, "is_carrier", False) or getattr(u, "role", None) == "CARRIER":
            # Показываем все активные инвайты для перевозчика
            qs = qs.filter(
                carrier=u,
                is_active=True,
                initiator__in=[Offer.Initiator.CUSTOMER, Offer.Initiator.LOGISTIC],
            )
        else:
            qs = (
                qs.filter(is_active=True)
                .filter(
                    Q(cargo__customer=u)
                    | Q(cargo__created_by=u)
                    | Q(logistic=u)
                    | Q(intermediary=u)
                )
                .distinct()
            )

        qs = _apply_common_filters(qs, request.query_params)
        page = self.paginate_queryset(qs)
        ser = self.get_serializer(page or qs, many=True)
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)

    @extend_schema(responses=OfferDetailSerializer)
    def retrieve(self, request, *args, **kwargs):
        obj = self.get_object()
        return Response(self.get_serializer(obj).data)

    @extend_schema(
        tags=["offers"],
        summary="Принять оффер",
        description="Акцепт оффера текущим пользователем. При взаимном акцепте создаётся заказ.",
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
        print("\n[VIEW accept]")
        print("offer.id =", offer.id, "deal_type =", offer.deal_type)
        print("user.id =", request.user.id, "role =", getattr(request.user, "role", None))
        print(
            "flags BEFORE:",
            "customer =",
            offer.accepted_by_customer,
            "carrier =",
            offer.accepted_by_carrier,
            "logistic =",
            offer.accepted_by_logistic,
        )
        print(
            "offer.carrier_id =",
            offer.carrier_id,
            "offer.logistic_id =",
            offer.logistic_id,
            "offer.intermediary_id =",
            offer.intermediary_id,
        )
        print(
            "cargo.customer_id =",
            getattr(offer.cargo, "customer_id", None),
            "cargo.created_by_id =",
            getattr(offer.cargo, "created_by_id", None),
        )

        try:
            offer.accept_by(request.user)
        except PermissionDenied as e:
            return Response({"detail": str(e)}, status=status.HTTP_403_FORBIDDEN)

        # Обновляем offer, чтобы увидеть созданный Order
        offer.refresh_from_db()
        print(
            "[VIEW accept] flags AFTER:",
            "customer =",
            offer.accepted_by_customer,
            "carrier =",
            offer.accepted_by_carrier,
            "logistic =",
            offer.accepted_by_logistic,
        )
        print("[VIEW accept] is_handshake =", offer.is_handshake)
        print("[VIEW accept] order_id =", getattr(getattr(offer, "order", None), "id", None))

        order = getattr(offer, "order", None)

        return Response(
            {
                "detail": "Принято",
                "accepted_by_customer": offer.accepted_by_customer,
                "accepted_by_carrier": offer.accepted_by_carrier,
                "accepted_by_logistic": offer.accepted_by_logistic,
                "order_id": order.id if order else None,
            },
            status=status.HTTP_200_OK,
        )

    def _create_order_from_offer(self, offer, accepted_by):
        """
        Создаёт заказ на основе оффера после взаимного акцепта.
        """
        logistic_user = offer.intermediary or offer.logistic

        # Если принял перевозчик — водитель известен
        if accepted_by.role == "CARRIER":
            status = Order.OrderStatus.PENDING
            carrier = accepted_by
        else:
            # Логист принял → водитель неизвестен
            status = Order.OrderStatus.NO_DRIVER
            carrier = None

        order = Order.objects.create(
            offer=offer,
            cargo=offer.cargo,
            customer=offer.customer,
            carrier=carrier,
            logistic=logistic_user,
            created_by=logistic_user or offer.customer,
            status=status,
            currency=offer.currency,
            price_total=offer.price,
            payment_method=offer.payment_method,
            route_distance_km=offer.route_distance_km,
        )

        return order

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

        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)

        with transaction.atomic():
            offer.make_counter(
                price_value=ser.validated_data["price_value"],
                price_currency=ser.validated_data.get("price_currency"),
                payment_method=ser.validated_data.get("payment_method"),
                message=ser.validated_data.get("message"),
                by_user=request.user,
            )

        return Response(
            OfferDetailSerializer(offer).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["offers"],
        summary="Инвайт перевозчику (Заказчик)",
        description="Заказчик отправляет персональное предложение перевозчику на свой груз.",
        request=OfferInviteSerializer,
        responses=OfferDetailSerializer,
    )
    @action(detail=False, methods=["post"])
    def invite(self, request):
        ser = self.get_serializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        with transaction.atomic():
            offer = ser.save()
        return Response(OfferDetailSerializer(offer).data, status=status.HTTP_201_CREATED)
