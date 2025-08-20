from rest_framework import generics, permissions
from drf_spectacular.utils import extend_schema
from .models import Cargo
from .serializers import CargoCreateSerializer, CargoListSerializer
from ..accounts.permissions import IsCustomer

@extend_schema(tags=["loads"])
class CargoCreateView(generics.CreateAPIView):
    permission_classes = [permissions.IsAuthenticated, IsCustomer]
    serializer_class = CargoCreateSerializer
    def perform_create(self, serializer):
        serializer.save(customer=self.request.user)

@extend_schema(tags=["loads"])
class MyCargosView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated, IsCustomer]
    serializer_class = CargoListSerializer
    def get_queryset(self):
        return Cargo.objects.filter(customer=self.request.user)