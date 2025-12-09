import uuid
from django.contrib.auth import get_user_model
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .filters import OrderFilter
from .models import Order, OrderStatusHistory
from .permissions import IsOrderParticipant
from .serializers import (
    OrderDetailSerializer,
    OrderDocumentSerializer,
    OrderListSerializer,
    OrderStatusHistorySerializer,
    OrderDriverStatusUpdateSerializer,
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
            return qs.filter(created_by=user)

        if role == "CUSTOMER":
            return qs.filter(customer=user)

        if role == "CARRIER":
            return qs.filter(carrier=user)

        return qs.none()

    def perform_create(self, serializer):
        user = self.request.user

        order = serializer.save(created_by=user)

        if user.role == "logistic":
            if order.carrier is None:
                order.status = order.OrderStatus.NO_DRIVER
            else:
                order.status = order.OrderStatus.NEW

            order.save(update_fields=["status"])

        return order

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

    @action(detail=True, methods=["get"], url_path="status-history")
    def status_history(self, request, pk=None):
        order = self.get_object()
        qs = order.status_history.all()
        ser = self.get_serializer(qs, many=True)
        return Response(ser.data, http_status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="invite-by-id")
    def invite_by_id(self, request, pk=None):
        from .serializers import InviteByIdSerializer

        order = self.get_object()
        user = request.user

        # 1. Только логист (создатель заказа) может приглашать
        if order.created_by_id != user.id:
            return Response({"detail": "Можно приглашать только в свои заказы"}, status=403)

        # 2. Можно приглашать только статус NO_DRIVER
        if order.status != Order.OrderStatus.NO_DRIVER:
            return Response({"detail": "У заказа уже есть водитель"}, status=400)

        # ---- Валидируем данные ----
        ser = InviteByIdSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        driver_id = ser.validated_data["driver_id"]

        # 3. Проверяем перевозчика
        try:
            driver = User.objects.get(id=driver_id, role="CARRIER")
        except User.DoesNotExist:
            return Response({"detail": "Перевозчик с таким ID не найден"}, status=404)

        # 4. Записываем приглашённого перевозчика
        order.invited_carrier = driver
        order.save(update_fields=["invited_carrier"])

        return Response({"detail": "Перевозчик приглашён"}, status=200)

    @action(detail=True, methods=["post"], url_path="generate-invite")
    def generate_invite(self, request, pk=None):
        order = self.get_object()
        user = request.user

        if order.created_by_id != user.id:
            return Response({"detail": "Нет доступа"}, status=403)

        if order.status != Order.OrderStatus.NO_DRIVER:
            return Response({"detail": "У заказа уже есть водитель"}, status=400)

        # создать токен
        token = uuid.uuid4()
        order.invite_token = token
        order.save(update_fields=["invite_token"])

        invite_url = f"https://moshin.uz/invite-order/{token}"

        return Response({"invite_url": invite_url}, status=200)

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

        # назначаем перевозчика
        order.carrier = user
        order.status = Order.OrderStatus.PENDING
        order.invite_token = None  # токен больше не нужен
        order.save(update_fields=["carrier", "status", "invite_token"])

        return Response({"detail": "Вы назначены перевозчиком заказа", "order_id": order.id})
