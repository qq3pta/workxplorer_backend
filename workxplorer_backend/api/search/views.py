from rest_framework import generics, permissions
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from ..accounts.permissions import IsCarrier
from ..loads.models import Cargo, CargoStatus
from ..loads.serializers import CargoListSerializer

@extend_schema(tags=["search"])
class CargoSearchView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated, IsCarrier]
    serializer_class = CargoListSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["origin_city", "destination_city"]

    def get_queryset(self):
        qs = Cargo.objects.filter(status=CargoStatus.POSTED)
        min_w = self.request.query_params.get("min_weight")
        max_w = self.request.query_params.get("max_weight")
        if min_w: qs = qs.filter(weight_kg__gte=min_w)
        if max_w: qs = qs.filter(weight_kg__lte=max_w)
        return qs.order_by("-created_at")