from api.geo.services import geocode_city
from django.contrib.gis.measure import D
from django.db.models import F, FloatField
from django.db.models.expressions import Func
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions
from rest_framework.exceptions import ValidationError

from ..accounts.permissions import IsCarrier
from ..loads.models import Cargo, CargoStatus
from ..loads.serializers import CargoListSerializer


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

        # Фильтры по весу
        min_w = qp.get("min_weight")
        max_w = qp.get("max_weight")
        if min_w:
            qs = qs.filter(weight_kg__gte=min_w)
        if max_w:
            qs = qs.filter(weight_kg__lte=max_w)

        # Фильтр "Откуда" по радиусу
        oc = qp.get("origin_city")
        occ = qp.get("origin_country") or ""
        r1 = qp.get("origin_radius_km")
        if oc and r1:
            try:
                center = geocode_city(occ, oc)
                radius_km = float(r1)
                qs = qs.filter(origin_point__dwithin=(center, D(km=radius_km)))
            except ValueError:
                # Радиус введён не числом
                raise ValidationError({"origin_radius_km": "Должен быть числом (км)."})
            except Exception:
                # Геокод не удался — фильтр не применяем
                pass

        # Фильтр "Куда" по радиусу
        dc = qp.get("destination_city")
        dcc = qp.get("destination_country") or ""
        r2 = qp.get("destination_radius_km")
        if dc and r2:
            try:
                center = geocode_city(dcc, dc)
                radius_km2 = float(r2)
                qs = qs.filter(dest_point__dwithin=(center, D(km=radius_km2)))
            except ValueError:
                raise ValidationError({"destination_radius_km": "Должен быть числом (км)."})
            except Exception:
                pass

        # Фильтр по типу транспорта (если передан — валидируем по enum и применяем)
        tt = qp.get("transport_type")
        if tt:
            try:
                tt_field = Cargo._meta.get_field("transport_type")
                allowed = [c[0] for c in (tt_field.choices or [])]
                if allowed and tt not in allowed:
                    raise ValidationError({"transport_type": f"Недопустимое значение. Допустимые: {', '.join(allowed)}."})
            except ValidationError:
                raise
            except Exception:
                # если поле без choices — просто применим фильтр
                pass
            qs = qs.filter(transport_type=tt)

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