from django.contrib.gis.measure import D
from django.db.models import Avg, F, FloatField
from django.db.models.expressions import Func
from django.db.models.functions import Coalesce
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions
from rest_framework.exceptions import ValidationError

from api.geo.services import geocode_city

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

        min_w = qp.get("min_weight")
        max_w = qp.get("max_weight")
        if min_w:
            qs = qs.filter(weight_kg__gte=min_w)
        if max_w:
            qs = qs.filter(weight_kg__lte=max_w)

        oc = qp.get("origin_city")
        occ = qp.get("origin_country") or ""
        r1 = qp.get("origin_radius_km")
        if oc and r1:
            try:
                center = geocode_city(occ, oc)
                radius_km = float(r1)
                qs = qs.filter(origin_point__dwithin=(center, D(km=radius_km)))
            except ValueError as err:
                raise ValidationError({"origin_radius_km": "Должен быть числом (км)."}) from err
            except Exception:
                pass

        dc = qp.get("destination_city")
        dcc = qp.get("destination_country") or ""
        r2 = qp.get("destination_radius_km")
        if dc and r2:
            try:
                center = geocode_city(dcc, dc)
                radius_km2 = float(r2)
                qs = qs.filter(dest_point__dwithin=(center, D(km=radius_km2)))
            except ValueError as err:
                raise ValidationError(
                    {"destination_radius_km": "Должен быть числом (км)."}
                ) from err
            except Exception:
                pass

        tt = qp.get("transport_type")
        if tt:
            try:
                tt_field = Cargo._meta.get_field("transport_type")
                allowed = [c[0] for c in (tt_field.choices or [])]
                if allowed and tt not in allowed:
                    raise ValidationError(
                        {
                            "transport_type": f"Недопустимое значение. Допустимые: {', '.join(allowed)}."
                        }
                    )
            except ValidationError:
                raise
            except Exception:
                pass
            qs = qs.filter(transport_type=tt)

        price_currency = qp.get("price_currency")
        if price_currency:
            qs = qs.filter(price_currency=price_currency)

        qs = qs.annotate(price_total_uzs=Coalesce("price_uzs", "price_value"))

        price_min = qp.get("price_min")
        price_max = qp.get("price_max")

        if price_min:
            qs = qs.filter(price_total_uzs__gte=price_min)
        if price_max:
            qs = qs.filter(price_total_uzs__lte=price_max)

        qs = qs.annotate(customer_rating=Avg("customer__ratings_received__score"))

        rating_min = qp.get("rating_min")
        rating_max = qp.get("rating_max")

        if rating_min:
            qs = qs.filter(customer_rating__gte=rating_min)
        if rating_max:
            qs = qs.filter(customer_rating__lte=rating_max)

        volume_min = qp.get("volume_min")
        volume_max = qp.get("volume_max")

        if volume_min:
            qs = qs.filter(volume_m3__gte=volume_min)
        if volume_max:
            qs = qs.filter(volume_m3__lte=volume_max)

        axles_min = qp.get("axles_min")
        axles_max = qp.get("axles_max")

        if axles_min:
            qs = qs.filter(axles__gte=axles_min)
        if axles_max:
            qs = qs.filter(axles__lte=axles_max)

        qs = qs.annotate(path_m=DistanceGeography(F("origin_point"), F("dest_point")))
        qs = qs.annotate(path_km=F("path_m") / 1000.0)

        order = qp.get("order")
        if order in [
            "price_total_uzs",
            "-price_total_uzs",
            "customer_rating",
            "-customer_rating",
            "volume_m3",
            "-volume_m3",
            "axles",
            "-axles",
            "path_km",
            "-path_km",
            "created_at",
            "-created_at",
        ]:
            qs = qs.order_by(order)
        else:
            qs = qs.order_by("-created_at")

        return qs
