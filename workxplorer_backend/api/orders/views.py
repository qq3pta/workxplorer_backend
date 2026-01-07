import uuid

from decimal import Decimal
from django.db.models import Q, F
from common.utils import convert_to_uzs
from django.contrib.auth import get_user_model
from django.db import models
from drf_spectacular.utils import extend_schema
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated

from rest_framework.response import Response

from .models import Order, OrderStatusHistory
from api.offers.models import Offer
from .permissions import IsOrderParticipant
from .serializers import (
    InviteByIdSerializer,
    OrderDetailSerializer,
    OrderDocumentSerializer,
    OrderDriverStatusUpdateSerializer,
    OrderListSerializer,
    OrderStatusHistorySerializer,
)

User = get_user_model()


def _apply_orders_filters(qs, p):
    # ---------- UUID ----------
    if p.get("uuid"):
        try:
            qs = qs.filter(id=int(p["uuid"]))
        except ValueError:
            return qs.none()

    if p.get("cargo_uuid"):
        qs = qs.filter(cargo__uuid=p["cargo_uuid"])

    # ---------- ГОРОДА ----------
    if p.get("origin_city"):
        qs = qs.filter(cargo__origin_city__iexact=p["origin_city"])
    if p.get("destination_city"):
        qs = qs.filter(cargo__destination_city__iexact=p["destination_city"])

    # ---------- ДАТЫ ----------
    if p.get("load_date"):
        qs = qs.filter(cargo__load_date=p["load_date"])
    if p.get("load_date_from"):
        qs = qs.filter(cargo__load_date__gte=p["load_date_from"])
    if p.get("load_date_to"):
        qs = qs.filter(cargo__load_date__lte=p["load_date_to"])
    if p.get("delivery_date_from"):
        qs = qs.filter(cargo__delivery_date__gte=p["delivery_date_from"])
    if p.get("delivery_date_to"):
        qs = qs.filter(cargo__delivery_date__lte=p["delivery_date_to"])

    # ---------- TRANSPORT ----------
    if p.get("transport_type"):
        qs = qs.filter(cargo__transport_type=p["transport_type"])

    # ---------- ВЕС ----------
    try:
        if p.get("min_weight"):
            qs = qs.filter(cargo__weight_kg__gte=float(p["min_weight"]) * 1000)
        if p.get("max_weight"):
            qs = qs.filter(cargo__weight_kg__lte=float(p["max_weight"]) * 1000)
    except ValueError:
        pass

    # ---------- ПОИСК ----------
    q = p.get("q") or p.get("company")
    if q:
        qs = qs.filter(
            Q(customer__company_name__icontains=q)
            | Q(customer__username__icontains=q)
            | Q(customer__email__icontains=q)
            | Q(carrier__company_name__icontains=q)
            | Q(carrier__username__icontains=q)
            | Q(carrier__email__icontains=q)
        )

    # ---------- СОРТИРОВКА ----------
    allowed = {
        "created_at",
        "-created_at",
        "price_uzs_anno",
        "-price_uzs_anno",
        "cargo__load_date",
        "-cargo__load_date",
        "cargo__delivery_date",
        "-cargo__delivery_date",
    }

    order = p.get("order")
    return qs.order_by(order) if order in allowed else qs.order_by("-created_at")


class OrdersViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all().select_related(
        "cargo",
        "customer",
        "carrier",
        "logistic",
        "created_by",
        "offer",
    )
    permission_classes = [IsAuthenticated, IsOrderParticipant]
    parser_classes = (JSONParser, MultiPartParser, FormParser)

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        p = self.request.query_params

        # ---------- Ролевая выборка ----------
        if not (user.is_staff or user.is_superuser):
            role = getattr(user, "role", None)
            as_role = p.get("as_role")

            if role == "LOGISTIC":
                if as_role == "customer":
                    qs = qs.filter(customer=user)
                else:
                    qs = qs.filter(
                        models.Q(logistic=user)
                        | models.Q(created_by=user)
                        | models.Q(cargo__created_by=user)
                        | models.Q(offer__logistic=user)
                        | models.Q(offer__intermediary=user)
                    ).distinct()

            elif role == "CUSTOMER":
                qs = qs.filter(customer=user)

            elif role == "CARRIER":
                qs = qs.filter(carrier=user)

            else:
                qs = qs.none()

        status_param = p.get("status")
        if status_param:
            qs = qs.filter(status=status_param)

        # ---------- Аннотация цены в UZS ----------
        qs = qs.annotate(price_uzs_anno=F("offer__price_value"))

        currency = p.get("price_currency")
        min_price = p.get("min_price")
        max_price = p.get("max_price")

        # если фронт передал валюту — фильтруем по ней (как раньше)
        if currency:
            qs = qs.filter(offer__price_currency=currency)

        def _to_uzs(value: str) -> Decimal:
            val = Decimal(value)
            # если указали валюту, конвертируем min/max в UZS
            return convert_to_uzs(val, currency) if currency else val

        try:
            if min_price not in (None, ""):
                qs = qs.filter(price_uzs_anno__gte=_to_uzs(min_price))

            if max_price not in (None, ""):
                qs = qs.filter(price_uzs_anno__lte=_to_uzs(max_price))
        except Exception:
            pass

        qs = _apply_orders_filters(qs, p)

        return qs

    def get_serializer_class(self):
        if self.action == "list":
            return OrderListSerializer
        if self.action in {"retrieve", "create", "update", "partial_update"}:
            return OrderDetailSerializer
        if self.action == "driver_status":
            return OrderDriverStatusUpdateSerializer
        if self.action == "status_history":
            return OrderStatusHistorySerializer
        if self.action == "documents" and self.request.method == "POST":
            return OrderDocumentSerializer
        return OrderDetailSerializer

    @action(detail=True, methods=["get", "patch"], url_path="driver-status")
    def driver_status(self, request, pk=None):
        order = self.get_object()
        user = request.user

        if request.method == "GET":
            return Response(
                {
                    "order_id": order.id,
                    "driver_status": order.driver_status,
                    "order_status": order.status,
                    "loading_datetime": order.loading_datetime,
                    "unloading_datetime": order.unloading_datetime,
                },
                status=http_status.HTTP_200_OK,
            )

        if user.id != order.carrier_id:
            return Response(
                {"detail": "Только перевозчик может менять статус водителя."},
                status=http_status.HTTP_403_FORBIDDEN,
            )

        allowed = ["stopped", "en_route", "problem"]

        ser = self.get_serializer(order, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        new_status = ser.validated_data.get("driver_status")

        if new_status not in allowed:
            return Response(
                {"detail": f"Недопустимый статус. Разрешено: {', '.join(allowed)}"},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        old_status = order.driver_status
        ser.save()

        if new_status != old_status:
            OrderStatusHistory.objects.create(
                order=order,
                old_status=old_status,
                new_status=new_status,
                user=user,
            )

        return Response(
            {"order_id": order.id, "old_status": old_status, "new_status": new_status},
            status=http_status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get", "post"], url_path="documents")
    def documents(self, request, pk=None):
        order = self.get_object()

        if request.method == "GET":
            qs = order.documents.all()
            category = request.query_params.get("category")
            if category:
                qs = qs.filter(category=category)

            ser = OrderDocumentSerializer(qs, many=True, context=self.get_serializer_context())
            return Response(ser.data, http_status.HTTP_200_OK)

        ser = self.get_serializer(data=request.data, context=self.get_serializer_context())
        ser.is_valid(raise_exception=True)
        ser.save(order=order, uploaded_by=request.user)

        return Response(ser.data, http_status.HTTP_201_CREATED)

    @extend_schema(
        tags=["orders"],
        summary="Подтверждение условий заказа Перевозчиком/Водителем",
        description="Перевозчик, принявший инвайт, подтверждает условия и переводит заказ в рабочий статус.",
        # Предполагается, что OrderDetailSerializer существует
        responses={200: OrderDetailSerializer},
    )
    @action(detail=True, methods=["post"], url_path="confirm-terms")
    def confirm_terms(self, request, pk=None):
        order = self.get_object()
        user = request.user

        # 1. Проверка доступа: должен быть назначенным перевозчиком
        if user.role != "CARRIER" or order.carrier != user:
            return Response(
                {"detail": "Только назначенный перевозчик может подтвердить условия."},
                status=http_status.HTTP_403_FORBIDDEN,
            )

        # 2. Проверка статуса (должен быть назначен, но не запущен)
        if order.status != Order.OrderStatus.NO_DRIVER:
            return Response(
                {"detail": "Заказ уже в работе или условия были подтверждены ранее."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        # 3. Установка флага и перевод в рабочий статус
        order.carrier_accepted_terms = True
        order.status = Order.OrderStatus.PENDING  # Переводим в рабочий статус
        order.save(update_fields=["carrier_accepted_terms", "status"])

        serializer = self.get_serializer(order)
        return Response(serializer.data, status=http_status.HTTP_200_OK)

    @action(detail=True, methods=["get"], url_path="status-history")
    def status_history(self, request, pk=None):
        order = self.get_object()
        qs = order.status_history.all()
        ser = self.get_serializer(qs, many=True)
        return Response(ser.data, http_status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="invite-by-id",
        serializer_class=InviteByIdSerializer,
    )
    def invite_by_id(self, request, pk=None):
        order = self.get_object()
        user = request.user

        if order.created_by_id != user.id:
            return Response(
                {"detail": "Можно приглашать только в свои заказы"},
                status=403,
            )

        if order.status != Order.OrderStatus.NO_DRIVER:
            return Response(
                {"detail": "У заказа уже есть водитель"},
                status=400,
            )

        ser = InviteByIdSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        driver_id = ser.validated_data["driver_id"]

        try:
            carrier = User.objects.get(id=driver_id, role="CARRIER")
        except User.DoesNotExist:
            return Response(
                {"detail": "Перевозчик с таким ID не найден"},
                status=404,
            )

        offer = Offer.objects.filter(
            cargo=order.cargo,
            carrier=carrier,
        ).first()

        if not offer:
            offer = Offer.objects.create(
                cargo=order.cargo,
                carrier=carrier,
                initiator=Offer.Initiator.CUSTOMER,
                deal_type=Offer.DealType.CUSTOMER_CARRIER,
            )

        # 🔥 КРИТИЧНО: СБРОС СОСТОЯНИЯ
        offer.is_active = True
        offer.accepted_by_customer = False
        offer.accepted_by_carrier = False
        offer.accepted_by_logistic = False
        offer.response_status = None

        offer.save(
            update_fields=[
                "is_active",
                "accepted_by_customer",
                "accepted_by_carrier",
                "accepted_by_logistic",
                "response_status",
            ]
        )

        order.offer = offer
        order.save(update_fields=["offer"])
        order.invited_carrier = carrier

        # Генерируем токен
        token = uuid.uuid4()
        order.invite_token = token
        order.save(update_fields=["invited_carrier", "invite_token"])

        # ✅ ВОТ ЭТОГО НЕ ХВАТАЛО
        return Response(
            {
                "detail": "Перевозчик успешно приглашён",
                "order_id": order.id,
                "carrier_id": carrier.id,
                "invite_token": str(token),
            },
            status=200,
        )

    @action(detail=True, methods=["post"], url_path="generate-invite")
    def generate_invite(self, request, pk=None):
        order = self.get_object()
        user = request.user

        if order.created_by_id != user.id:
            return Response({"detail": "Нет доступа"}, status=403)

        if order.status != Order.OrderStatus.NO_DRIVER:
            return Response({"detail": "У заказа уже есть водитель"}, status=400)

        # генерируем токен
        token = uuid.uuid4()

        # сохраняем токен в заказе (опционально)
        order.invite_token = token
        order.save(update_fields=["invite_token"])

        # возвращаем только токен, фронт сам соберет URL
        return Response({"invite_token": str(token)}, status=200)

    @action(detail=False, methods=["post"], url_path="accept-invite")
    def accept_invite(self, request):
        token = request.data.get("token")
        user = request.user

        if not token:
            return Response({"detail": "token обязателен"}, status=400)

        try:
            order = Order.objects.get(
                invite_token=token,
                status=Order.OrderStatus.NO_DRIVER,
            )
        except Order.DoesNotExist:
            return Response({"detail": "Приглашение недействительно"}, status=404)

        if user.role != "CARRIER":
            return Response({"detail": "Только перевозчики могут принять заказ"}, status=403)

        # ✅ ТОЛЬКО ORDER
        order.carrier = user
        order.invite_token = None
        order.status = Order.OrderStatus.NO_DRIVER
        order.carrier_accepted_terms = False

        order.save(
            update_fields=[
                "carrier",
                "invite_token",
                "status",
                "carrier_accepted_terms",
            ]
        )

        return Response(
            {
                "detail": "Инвайт принят. Подтвердите оффер.",
                "order_id": order.id,
                "next_action": "accept_offer",
            },
            status=200,
        )
