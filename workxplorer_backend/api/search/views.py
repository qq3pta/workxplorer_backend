from rest_framework import generics, permissions
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from django.db.models import F, FloatField
from django.db.models.expressions import Func

from ..accounts.permissions import IsCarrier
from ..loads.models import Cargo, CargoStatus
from ..loads.serializers import CargoListSerializer
from api.geo.services import geocode_city
from django.contrib.gis.measure import D


class DistanceGeography(Func):
    """
    Корректный расчёт расстояния в метрах по WGS84:
    ST_Distance(a::geography, b::geography)
    """
    output_field = FloatField()
    function = "ST_Distance"

    def as_sql(self, compiler, connection, **extra_context):
        lhs, lp = compiler.compile(self.source_expressions[0])
        rhs, rp = compiler.compile(self.source_expressions[1])
        sql = f"ST_Distance({lhs}::geography, {rhs}::geography)"
        return sql, lp + rp


@extend_schema(tags=["search"])
class CargoSearchView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated, IsCarrier]
    serializer_class = CargoListSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["origin_city", "destination_city"]

    def get_queryset(self):
        qs = Cargo.objects.filter(status=CargoStatus.POSTED)

        qp = self.request.query_params
        min_w = qp.get("min_weight")
        max_w = qp.get("max_weight")
        if min_w:
            qs = qs.filter(weight_kg__gte=min_w)
        if max_w:
            qs = qs.filter(weight_kg__lte=max_w)

        # Радиус "откуда"
        oc = qp.get("origin_city")
        occ = qp.get("origin_country") or ""
        r1 = qp.get("origin_radius_km")
        if oc and r1:
            try:
                center = geocode_city(occ, oc)
                qs = qs.filter(origin_point__dwithin=(center, D(km=float(r1))))
            except Exception:
                pass

        # Радиус "куда"
        dc = qp.get("destination_city")
        dcc = qp.get("destination_country") or ""
        r2 = qp.get("destination_radius_km")
        if dc and r2:
            try:
                center = geocode_city(dcc, dc)
                qs = qs.filter(dest_point__dwithin=(center, D(km=float(r2))))
            except Exception:
                pass

        # Расстояние (метры → км)
        qs = qs.annotate(path_m=DistanceGeography(F("origin_point"), F("dest_point")))
        qs = qs.annotate(path_km=F("path_m") / 1000.0)

        # Сортировка
        order = qp.get("order")
        if order == "path_km":
            qs = qs.order_by("path_m")
        elif order == "-path_km":
            qs = qs.order_by("-path_m")
        else:
            qs = qs.order_by("-created_at")

        return qs