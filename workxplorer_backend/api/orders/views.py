import uuid

from decimal import Decimal
from django.db.models import Q, F
from common.utils import convert_to_uzs
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.db import models
from django.utils import timezone
from datetime import timedelta
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import AllowAny

from rest_framework.response import Response

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from common.ws_utils import to_ws_safe


from .models import Order, OrderStatusHistory, DriverLocation
from api.offers.models import Offer
from .permissions import IsOrderParticipant
from .serializers import (
    InviteByIdSerializer,
    OrderDetailSerializer,
    OrderDocumentSerializer,
    OrderDriverStatusUpdateSerializer,
    OrderListSerializer,
    OrderStatusHistorySerializer,
    InvitePreviewSerializer,
    PrivacyToggleSerializer,
    GPSUpdateSerializer,
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
    queryset = (
        Order.objects.all()
        .select_related(
            "cargo",
            "customer",
            "carrier",
            "logistic",
            "created_by",
            "offer",
            "offer__carrier",
            "offer__logistic",
            "carrier__gps",
        )
        .prefetch_related(
            "documents",
            "ratings",
            "ratings__rated_by",
            "ratings__rated_user",
            "payments",
        )
        .annotate(documents_count=models.Count("documents", distinct=True))
    )
    permission_classes = [IsAuthenticated, IsOrderParticipant]
    parser_classes = (JSONParser, MultiPartParser, FormParser)

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        p = self.request.query_params

        if not (user.is_staff or user.is_superuser):
            role = getattr(user, "role", None)

            if role == "LOGISTIC":
                # Support query param used by clients: `as_role`.
                raw_role = (p.get("as_role") or "").strip().lower()

                role_aliases = {
                    "customer": "customer",
                    "orders": "customer",
                    "logistic": "logistic",
                    "vezu": "logistic",
                    "carrier": "logistic",
                }
                as_role = role_aliases.get(raw_role, "")

                if as_role == "customer":
                    qs = qs.filter(customer=user)

                elif as_role == "logistic":
                    qs = qs.filter(
                        Q(logistic=user)
                        | Q(created_by=user)
                        | Q(cargo__created_by=user)
                        | Q(offer__logistic=user)
                        | Q(offer__intermediary=user)
                    )

                else:
                    qs = qs.filter(
                        Q(logistic=user)
                        | Q(created_by=user)
                        | Q(cargo__created_by=user)
                        | Q(offer__logistic=user)
                        | Q(offer__intermediary=user)
                        | Q(customer=user)
                    )

                qs = qs.distinct()

            elif role == "CUSTOMER":
                qs = qs.filter(customer=user)

            elif role == "CARRIER":
                qs = qs.filter(carrier=user)

            else:
                qs = qs.none()

        # ---------- STATUS ----------
        status_param = p.get("status")
        if status_param:
            qs = qs.filter(status=status_param)

        # ---------- ЦЕНА ----------
        qs = qs.annotate(price_uzs_anno=F("offer__price_value"))

        currency = p.get("price_currency")
        min_price = p.get("min_price")
        max_price = p.get("max_price")

        if currency:
            qs = qs.filter(offer__price_currency=currency)

        def _to_uzs(value: str) -> Decimal:
            val = Decimal(value)
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

        channel_layer = get_channel_layer()

        participants = {
            order.customer_id,
            order.carrier_id,
            order.logistic_id,
        }

        # Отправляем легковесное уведомление вместо полного сериализатора
        for user_id in filter(None, participants):
            message = {
                "type": "notify",
                "data": {
                    "event": "driver_status_changed",
                    "order_id": order.id,
                    # Keep explicit names for driver status changes.
                    "driver_status": new_status,
                    "driver_old_status": old_status,
                    "driver_new_status": new_status,
                    # Also include stable order status for tab grouping on clients.
                    "order_status": order.status,
                    "status": order.status,
                },
            }

            async_to_sync(channel_layer.group_send)(
                f"user_{user_id}",
                to_ws_safe(message),
            )

        return Response(
            {
                "order_id": order.id,
                # Stable order status (for clients that reuse generic status handlers).
                "order_status": order.status,
                "status": order.status,
                "old_status": order.status,
                "new_status": order.status,
                # Explicit driver status diff.
                "driver_status": new_status,
                "driver_old_status": old_status,
                "driver_new_status": new_status,
            },
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

        channel_layer = get_channel_layer()

        # Отправляем легковесное уведомление
        for user_id in filter(None, {order.customer_id, order.carrier_id, order.logistic_id}):
            message = {
                "type": "notify",
                "data": {
                    "event": "order_documents_added",
                    "order_id": order.id,
                    "document_id": ser.data["id"],
                    "category": ser.data["category"],
                },
            }

            async_to_sync(channel_layer.group_send)(
                f"user_{user_id}",
                to_ws_safe(message),
            )

        return Response(ser.data, http_status.HTTP_201_CREATED)

    @extend_schema(
        tags=["orders"],
        summary="Подтверждение условий заказа Перевозчиком/Водителем",
        description="Перевозчик, принявший инвайт, подтверждает условия и переводит заказ в рабочий статус.",
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
        order.status = Order.OrderStatus.PENDING
        order.save(update_fields=["carrier_accepted_terms", "status"])

        channel_layer = get_channel_layer()

        # Отправляем легковесное уведомление
        for user_id in filter(None, {order.customer_id, order.carrier_id, order.logistic_id}):
            message = {
                "type": "notify",
                "data": {
                    "event": "order_confirmed",
                    "order_id": order.id,
                    "status": order.status,
                },
            }

            async_to_sync(channel_layer.group_send)(
                f"user_{user_id}",
                to_ws_safe(message),
            )

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
            return Response({"detail": "Можно приглашать только в свои заказы"}, status=403)

        if order.status != Order.OrderStatus.NO_DRIVER:
            return Response({"detail": "У заказа уже есть водитель"}, status=400)

        ser = InviteByIdSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        driver_id = ser.validated_data["driver_id"]
        driver_price = ser.validated_data["driver_price"]
        driver_currency = ser.validated_data["driver_currency"]
        driver_payment_method = ser.validated_data["driver_payment_method"]

        try:
            carrier = User.objects.get(id=driver_id, role="CARRIER")
        except User.DoesNotExist:
            return Response({"detail": "Перевозчик с таким ID не найден"}, status=404)

        offer = Offer.objects.filter(cargo=order.cargo, carrier=carrier).first()

        if not offer:
            offer = Offer.objects.create(
                cargo=order.cargo,
                carrier=carrier,
                initiator=Offer.Initiator.CUSTOMER,
                deal_type=Offer.DealType.CUSTOMER_CARRIER,
            )

        offer.is_active = True
        offer.accepted_by_customer = False
        offer.accepted_by_carrier = False
        offer.accepted_by_logistic = False
        offer.response_status = None

        offer.driver_price = driver_price
        offer.driver_currency = driver_currency
        offer.driver_payment_method = driver_payment_method

        if user.role == "LOGISTIC":
            order.logistic = user
            offer.logistic = user

        offer.save(
            update_fields=[
                "driver_price",
                "driver_currency",
                "driver_payment_method",
                "is_active",
                "accepted_by_customer",
                "accepted_by_carrier",
                "accepted_by_logistic",
                "response_status",
                "logistic",
            ]
        )

        order.driver_price = driver_price

        order.driver_currency = driver_currency
        order.driver_payment_method = driver_payment_method

        if user.role == "LOGISTIC":
            order.logistic = user
            offer.logistic = user

        order.invited_carrier = carrier
        order.invite_token = uuid.uuid4()

        order.carrier_accepted_terms = False
        order.status = Order.OrderStatus.NO_DRIVER

        order.save(
            update_fields=[
                "driver_price",
                "driver_currency",
                "driver_payment_method",
                "invited_carrier",
                "invite_token",
                "carrier_accepted_terms",
                "status",
                "logistic",
            ]
        )

        channel_layer = get_channel_layer()

        participants = {
            order.customer_id,
            carrier.id,
            order.logistic_id,
        }

        # Отправляем легковесное уведомление
        for user_id in filter(None, participants):
            message = {
                "type": "notify",
                "data": {
                    "event": "order_invited_carrier",
                    "order_id": order.id,
                    "carrier_id": carrier.id,
                    "invite_token": str(order.invite_token),
                },
            }

            async_to_sync(channel_layer.group_send)(
                f"user_{user_id}",
                to_ws_safe(message),
            )

        return Response(
            {
                "detail": "Перевозчик успешно приглашён",
                "order_id": order.id,
                "carrier_id": carrier.id,
                "invite_token": str(order.invite_token),
                "driver_price": float(order.driver_price),
                "driver_currency": order.driver_currency,
                "driver_payment_method": order.driver_payment_method,
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

        driver_price = request.data.get("driver_price")
        driver_currency = request.data.get("driver_currency")
        driver_payment_method = request.data.get("driver_payment_method")

        if driver_price is not None:
            order.driver_price = driver_price

        if driver_currency is not None:
            order.driver_currency = driver_currency

        if driver_payment_method is not None:
            order.driver_payment_method = driver_payment_method

        token = uuid.uuid4()

        order.invite_token = token
        update_fields = ["invite_token"]

        if driver_price is not None:
            update_fields.append("driver_price")

        if driver_currency is not None:
            update_fields.append("driver_currency")

        if driver_payment_method is not None:
            update_fields.append("driver_payment_method")

        if getattr(user, "role", None) == "LOGISTIC":
            order.logistic = user
            update_fields.append("logistic")

        order.save(update_fields=update_fields)

        channel_layer = get_channel_layer()

        # Отправляем легковесное уведомление
        for user_id in filter(None, {order.customer_id, order.logistic_id}):
            message = {
                "type": "notify",
                "data": {
                    "event": "invite_generated",
                    "order_id": order.id,
                    "invite_token": str(token),
                },
            }

            async_to_sync(channel_layer.group_send)(
                f"user_{user_id}",
                to_ws_safe(message),
            )

        return Response(
            {
                "invite_token": str(token),
                "driver_price": float(order.driver_price) if order.driver_price else None,
                "driver_currency": order.driver_currency,
                "driver_payment_method": order.driver_payment_method,
            },
            status=200,
        )

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

        order.carrier = user
        order.invited_carrier = None
        order.invite_token = None
        order.carrier_accepted_terms = False
        if not order.logistic and getattr(order.created_by, "role", None) == "LOGISTIC":
            order.logistic = order.created_by
        order.save(
            update_fields=[
                "carrier",
                "invited_carrier",
                "invite_token",
                "carrier_accepted_terms",
                "logistic",
            ]
        )

        channel_layer = get_channel_layer()

        # Отправляем легковесное уведомление
        for user_id in filter(None, {order.customer_id, user.id, order.logistic_id}):
            message = {
                "type": "notify",
                "data": {
                    "event": "order_invite_accepted",
                    "order_id": order.id,
                    "carrier_id": user.id,
                },
            }

            async_to_sync(channel_layer.group_send)(
                f"user_{user_id}",
                to_ws_safe(message),
            )

        Offer.objects.filter(
            cargo=order.cargo,
            carrier=user,
        ).update(
            is_active=False,
            accepted_by_carrier=True,
        )

        return Response(
            {
                "detail": "Инвайт принят. Подтвердите оффер.",
                "order_id": order.id,
                "next_action": "accept_offer",
                "driver_price": float(order.driver_price) if order.driver_price else None,
            },
            status=200,
        )

    @action(detail=False, methods=["post"], url_path="decline-invite")
    def decline_invite(self, request):
        token = request.data.get("token")
        user = request.user

        if not token:
            return Response({"detail": "token обязателен"}, status=400)

        try:
            order = Order.objects.get(invite_token=token)
        except Order.DoesNotExist:
            return Response({"detail": "Инвайт не найден или уже недействителен"}, status=404)

        if user.role != "CARRIER":
            return Response({"detail": "Только перевозчик может отказаться от инвайта"}, status=403)

        if order.invited_carrier_id and order.invited_carrier_id != user.id:
            return Response({"detail": "Этот инвайт предназначен другому перевозчику"}, status=403)

        # очищаем инвайт
        order.invited_carrier = None
        order.invite_token = None
        order.carrier_accepted_terms = False
        order.status = Order.OrderStatus.NO_DRIVER

        order.save(
            update_fields=[
                "invited_carrier",
                "invite_token",
                "carrier_accepted_terms",
                "status",
            ]
        )

        channel_layer = get_channel_layer()

        # Отправляем легковесное уведомление
        for user_id in filter(None, {order.customer_id, user.id, order.logistic_id}):
            message = {
                "type": "notify",
                "data": {
                    "event": "order_invite_declined",
                    "order_id": order.id,
                    "carrier_id": user.id,
                },
            }

            async_to_sync(channel_layer.group_send)(
                f"user_{user_id}",
                to_ws_safe(message),
            )

        Offer.objects.filter(
            cargo=order.cargo,
            carrier=user,
        ).update(
            is_active=False,
            response_status="rejected",
        )

        return Response(
            {"detail": "Вы отказались от заказа"},
            status=200,
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="token",
                description="Invite token (UUID)",
                required=True,
                type=str,
                location=OpenApiParameter.QUERY,
            )
        ],
        responses={200: InvitePreviewSerializer},
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="invite-preview",
        permission_classes=[AllowAny],
    )
    def invite_preview(self, request):
        token = request.query_params.get("token")

        if not token:
            return Response({"detail": "token обязателен"}, status=400)

        try:
            order = Order.objects.select_related("cargo", "customer", "logistic", "created_by").get(
                invite_token=token
            )
        except Order.DoesNotExist:
            return Response({"detail": "Инвайт недействителен или истёк"}, status=404)

        cargo = order.cargo
        inviter = order.logistic or order.created_by or order.customer

        inviter_data = None
        if inviter:
            inviter_data = {
                "id": inviter.id,
                "role": getattr(inviter, "role", None),
                "name": inviter.get_full_name() or inviter.username,
                "company": getattr(inviter, "company_name", None),
            }

        data = {
            "order_id": order.id,
            "origin_city": getattr(cargo, "origin_city", None),
            "destination_city": getattr(cargo, "destination_city", None),
            "load_date": getattr(cargo, "load_date", None),
            "delivery_date": getattr(cargo, "delivery_date", None),
            "route_distance_km": getattr(order, "route_distance_km", None),
            "weight_kg": getattr(cargo, "weight_kg", None),
            "transport_type": getattr(cargo, "transport_type", None),
            "inviter": inviter_data,
            "driver_price": order.driver_price,
            "driver_currency": getattr(order, "driver_currency", None),
            "driver_payment_method": getattr(order, "driver_payment_method", None),
        }

        serializer = InvitePreviewSerializer(data)
        return Response(serializer.data, status=200)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel_order(self, request, pk=None):
        order = self.get_object()
        user = request.user

        if order.status not in [Order.OrderStatus.NO_DRIVER, Order.OrderStatus.PENDING]:
            return Response(
                {"detail": "Этот заказ нельзя отменить на данном этапе."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        if user not in [order.customer, order.carrier, order.logistic]:
            return Response(
                {"detail": "Вы не можете отменять чужой заказ."},
                status=http_status.HTTP_403_FORBIDDEN,
            )

        old_status = order.status
        order.status = "canceled"
        order.save(update_fields=["status"])

        channel_layer = get_channel_layer()

        # Отправляем легковесное уведомление
        for user_id in filter(None, {order.customer_id, order.carrier_id, order.logistic_id}):
            async_to_sync(channel_layer.group_send)(
                f"user_{user_id}",
                to_ws_safe(
                    {
                        "type": "notify",
                        "data": {
                            "event": "order_canceled",
                            "order_id": order.id,
                            "new_status": order.status,
                        },
                    }
                ),
            )

        if hasattr(user, "profile"):
            user.profile.cancelled_orders_count += 1
            user.profile.save(update_fields=["cancelled_orders_count"])

        OrderStatusHistory.objects.create(
            order=order,
            old_status=old_status,
            new_status=order.status,
            user=user,
        )

        return Response(
            {
                "detail": "Заказ успешно отменён",
                "order_id": order.id,
                "new_status": order.status,
            },
            status=http_status.HTTP_200_OK,
        )

    # ================= GPS TRACKING =================
    @extend_schema(
        request=GPSUpdateSerializer,
        responses={200: GPSUpdateSerializer},
    )
    @action(detail=False, methods=["post"], url_path="gps")
    def update_gps(self, request):
        user = request.user

        ser = GPSUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        lat = ser.validated_data["lat"]
        lng = ser.validated_data["lng"]
        speed = ser.validated_data.get("speed")

        point = Point(lng, lat, srid=4326)
        now = timezone.now()

        gps, _ = DriverLocation.objects.get_or_create(driver=user)

        # throttle 5–10 сек
        if gps.recorded_at and now - gps.recorded_at < timedelta(seconds=10):
            return Response({"ignored": True})

        gps.point = point
        gps.speed = speed
        gps.recorded_at = now
        gps.save(update_fields=["point", "speed", "recorded_at"])

        # ===== Найти активный заказ водителя =====
        order = (
            Order.objects.filter(carrier_id=user.id)
            .exclude(status__in=["finished", "canceled"])
            .only("id", "customer_id", "carrier_id", "logistic_id")
            .first()
        )

        # ===== WS =====
        if order:
            channel_layer = get_channel_layer()

            payload = {
                "event": "gps_updated",
                "order_id": order.id,
                "driver_location": {
                    "lat": lat,
                    "lng": lng,
                    "speed": speed,
                    "recorded_at": now.isoformat(),
                },
            }

            for user_id in filter(None, {order.customer_id, order.carrier_id, order.logistic_id}):
                async_to_sync(channel_layer.group_send)(
                    f"user_{user_id}",
                    to_ws_safe({"type": "notify", "data": payload}),
                )

        return Response(
            {
                "driver_location": {
                    "lat": lat,
                    "lng": lng,
                    "speed": speed,
                    "recorded_at": now.isoformat(),
                }
            }
        )

    @extend_schema(
        request=PrivacyToggleSerializer,
        examples=[
            OpenApiExample("Hide", value={"hide": True}),
            OpenApiExample("Show", value={"hide": False}),
        ],
    )
    @action(detail=True, methods=["post"], url_path="privacy-toggle")
    def privacy_toggle(self, request, pk=None):
        order = self.get_object()
        user = request.user

        serializer = PrivacyToggleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        hide = serializer.validated_data["hide"]

        if user.id == order.customer_id:
            order.customer_hide_contacts = bool(hide)
            order.save(update_fields=["customer_hide_contacts"])

        elif user.id == order.logistic_id:
            order.logistic_hide_contacts = bool(hide)
            order.save(update_fields=["logistic_hide_contacts"])

        else:
            return Response({"detail": "No permission"}, status=403)

        channel_layer = get_channel_layer()

        participants = {
            order.customer_id,
            order.logistic_id,
            order.carrier_id,
        }

        hidden = order.customer_hide_contacts or order.logistic_hide_contacts
        hidden_by = order.logistic_hide_contacts

        def _hidden_by_for(user_id):
            # The customer should not be blocked by a flag that represents
            # who hid their contacts for other participants.
            if user_id == order.customer_id:
                return False
            return bool(hidden_by)

        for user_id in filter(None, participants):
            async_to_sync(channel_layer.group_send)(
                f"user_{user_id}",
                to_ws_safe(
                    {
                        "type": "notify",
                        "data": {
                            "event": "order_privacy_changed",
                            "order_id": order.id,
                            "roles": {
                                "customer": {
                                    "hidden": bool(hidden),
                                    "hidden_by": _hidden_by_for(user_id),
                                }
                            },
                        },
                    }
                ),
            )

        return Response(
            {
                "roles": {
                    "customer": {
                        "hidden": bool(hidden),
                        "hidden_by": _hidden_by_for(user.id),
                    }
                }
            }
        )


class SharedOrderView(RetrieveAPIView):
    """
    Публичный просмотр заказа по share_token
    """

    queryset = Order.objects.all().select_related(
        "cargo",
        "customer",
        "carrier",
        "logistic",
        "created_by",
        "offer",
    )
    serializer_class = OrderDetailSerializer
    permission_classes = [AllowAny]
    lookup_field = "share_token"
