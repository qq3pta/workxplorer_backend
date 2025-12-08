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
