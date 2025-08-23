from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from .models import Cargo
from .choices import ModerationStatus
from .serializers import CargoPublishSerializer, CargoListSerializer
from ..accounts.permissions import IsCustomer  # логист тоже проходит

@extend_schema(tags=["loads"])
class PublishCargoView(generics.CreateAPIView):
    permission_classes = [permissions.IsAuthenticated, IsCustomer]
    serializer_class = CargoPublishSerializer

    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        cargo = s.save(customer=request.user, moderation_status=ModerationStatus.PENDING)
        return Response(
            {"message": "Заявка успешно опубликована и отправлена на модерацию", "id": cargo.id},
            status=status.HTTP_201_CREATED,
            headers=self.get_success_headers(s.data),
        )

@extend_schema(tags=["loads"])
class CargoDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAuthenticated, IsCustomer]
    serializer_class = CargoPublishSerializer

    def get_queryset(self):
        return Cargo.objects.filter(customer=self.request.user)

    def perform_update(self, serializer):
        obj = serializer.save()
        obj.refreshed_at = timezone.now()
        obj.save(update_fields=["refreshed_at"])

@extend_schema(tags=["loads"])
class CargoRefreshView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated, IsCustomer]

    def post(self, request, pk: int):
        try:
            obj = Cargo.objects.get(pk=pk, customer=request.user)
        except Cargo.DoesNotExist:
            return Response({"detail": "Не найдено"}, status=status.HTTP_404_NOT_FOUND)

        if (timezone.now() - obj.refreshed_at).total_seconds() < 15 * 60:
            return Response({"detail": "Можно обновлять раз в 15 минут"}, status=429)

        obj.refreshed_at = timezone.now()
        obj.save(update_fields=["refreshed_at"])
        return Response({"detail": "Обновлено"})

@extend_schema(tags=["loads"])
class MyCargosView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated, IsCustomer]
    serializer_class = CargoListSerializer

    def get_queryset(self):
        return Cargo.objects.filter(customer=self.request.user).order_by("-created_at")

@extend_schema(tags=["loads"])
class MyCargosBoardView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated, IsCustomer]
    serializer_class = CargoListSerializer

    def get_queryset(self):
        qs = Cargo.objects.filter(customer=self.request.user, status="POSTED")

        p = self.request.query_params
        if p.get("origin_city"):
            qs = qs.filter(origin_city__iexact=p["origin_city"])
        if p.get("destination_city"):
            qs = qs.filter(destination_city__iexact=p["destination_city"])
        if p.get("load_date"):
            qs = qs.filter(load_date=p["load_date"])
        if p.get("transport_type"):
            qs = qs.filter(transport_type=p["transport_type"])
        if p.get("id"):
            qs = qs.filter(id=p["id"])

        return qs.order_by("-refreshed_at")