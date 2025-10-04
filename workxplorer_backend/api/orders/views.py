from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .filters import OrderFilter
from .models import Order
from .permissions import IsOrderParticipant
from .serializers import (
    OrderDetailSerializer,
    OrderDocumentSerializer,
    OrderListSerializer,
    OrderStatusUpdateSerializer,
)


class OrdersViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.all().select_related("cargo", "customer", "carrier")
    permission_classes = [IsAuthenticated, IsOrderParticipant]
    filter_backends = [DjangoFilterBackend]
    filterset_class = OrderFilter
    parser_classes = (JSONParser, MultiPartParser, FormParser)

    def get_queryset(self):
        qs = super().get_queryset()
        u = getattr(self.request, "user", None)
        if not u or (not getattr(u, "is_staff", False) and not getattr(u, "is_superuser", False)):
            qs = qs.filter(Q(customer_id=u.id) | Q(carrier_id=u.id))
        return qs

    def get_serializer_class(self):
        if self.action == "list":
            return OrderListSerializer
        if self.action in {"retrieve", "create", "update", "partial_update"}:
            return OrderDetailSerializer
        if self.action == "set_status":
            return OrderStatusUpdateSerializer
        if self.action == "documents" and self.request.method == "POST":
            return OrderDocumentSerializer
        return OrderDetailSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx.setdefault("request", self.request)
        return ctx

    @action(detail=True, methods=["patch"], url_path="status")
    def set_status(self, request, pk=None):
        """Обновление статуса (валидация через OrderStatusUpdateSerializer)."""
        order = self.get_object()
        ser = self.get_serializer(order, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data, status=http_status.HTTP_200_OK)

    @action(detail=True, methods=["get", "post"], url_path="documents")
    def documents(self, request, pk=None):
        """
        GET  /orders/{id}/documents/ → список документов
        POST /orders/{id}/documents/ → загрузка файла (multipart/form-data)
        """
        order = self.get_object()

        if request.method == "GET":
            qs = order.documents.all()
            data = OrderDocumentSerializer(
                qs, many=True, context=self.get_serializer_context()
            ).data
            return Response(data, status=http_status.HTTP_200_OK)

        ser = self.get_serializer(data=request.data, context=self.get_serializer_context())
        ser.is_valid(raise_exception=True)
        ser.save(order=order, uploaded_by=request.user)
        return Response(ser.data, status=http_status.HTTP_201_CREATED)
