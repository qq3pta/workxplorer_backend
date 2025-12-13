import uuid

from django.contrib.auth import get_user_model
from django.db import models
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated

# from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .filters import OrderFilter
from .models import Order, OrderStatusHistory
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


class OrdersViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all().select_related("cargo", "customer", "carrier", "created_by")
    permission_classes = [IsAuthenticated, IsOrderParticipant]
    filter_backends = [DjangoFilterBackend]
    filterset_class = OrderFilter
    parser_classes = (JSONParser, MultiPartParser, FormParser)

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user

        if user.is_staff or user.is_superuser:
            return qs

        role = getattr(user, "role", None)

        if role == "LOGISTIC":
            return qs.filter(
                models.Q(logistic=user)
                | models.Q(created_by=user)
                | models.Q(cargo__created_by=user)
                | models.Q(offer__logistic=user)
                | models.Q(offer__intermediary=user)
                | models.Q(customer=user)
            ).distinct()

        if role == "CUSTOMER":
            return qs.filter(customer=user)

        if role == "CARRIER":
            return qs.filter(carrier=user)

        return qs.none()

    # def perform_create(self, serializer):
    #    user = self.request.user
    #    offer = serializer.validated_data.get("offer")

    # CASE 1: Customer manually confirms offer → creates order
    #    if offer and user.role == "CUSTOMER":
    #        logistic_user = offer.intermediary or offer.logistic

    #        return Order.objects.create(
    #            cargo=offer.cargo,
    #            customer=offer.customer,
    #            created_by=logistic_user or offer.customer,
    #            logistic=logistic_user,
    #            status=Order.OrderStatus.NO_DRIVER,
    #            currency=offer.currency,
    #            price_total=offer.price,
    #            route_distance_km=offer.route_distance_km,
    #        )

    # CASE 2: Logistic cannot create order manually — only through accepting an offer
    #    if user.role == "LOGISTIC":
    #        raise ValidationError(
    #            "Логисты не создают заказ вручную — заказ создаётся автоматически при принятии оффера."
    #        )

    # CASE 3: Carrier cannot create orders manually either
    #    raise ValidationError("Создание заказа возможно только через оффер.")

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

        # offer, created = Offer.objects.get_or_create(
        #    cargo=order.cargo,
        #    carrier=carrier,
        #    defaults={
        #        "initiator": Offer.Initiator.CUSTOMER,
        #        "logistic": user,
        #        "price_value": order.price_total or 0,
        #        "price_currency": order.currency,
        #        "message": "Приглашение через заказ",
        #        "is_active": True,
        #    },
        # )

        # if created:
        #    offer.send_create_notifications()

        # return Response(
        #    {
        #        "detail": "Перевозчик приглашён",
        #        "offer_id": offer.id,
        #        "invite_token": str(token),
        #    },
        #    status=200,
        # )

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
            order = Order.objects.get(invite_token=token, status=Order.OrderStatus.NO_DRIVER)
        except Order.DoesNotExist:
            return Response({"detail": "Приглашение недействительно"}, status=404)

        if user.role != "CARRIER":
            return Response({"detail": "Только перевозчики могут принять заказ"}, status=403)

        # Назначаем перевозчика
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

        # --------------------------------------------------------------

        return Response(
            {
                "detail": "Приглашение принято. Пожалуйста, подтвердите условия заказа.",
                "order_id": order.id,
                "requires_terms_confirmation": True,
            },
            status=200,
        )
