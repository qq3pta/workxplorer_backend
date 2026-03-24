from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from unidecode import unidecode

from .models import GeoPlace
from .serializers import CitySuggestResponseSerializer, CountrySuggestResponseSerializer


class SuggestThrottle(AnonRateThrottle):
    rate = "60/min"


def is_latin(text: str) -> bool:
    return unidecode(text).lower() == text.lower()


# ---------------- Countries ----------------
class CountrySuggestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [SuggestThrottle]

    @extend_schema(
        summary="Подсказки по странам",
        parameters=[
            OpenApiParameter(
                "q",
                description="Часть названия страны",
                required=False,
                type=OpenApiTypes.STR,
                location="query",
            ),
            OpenApiParameter(
                "limit",
                description="Максимум результатов (1..50, по умолчанию 10)",
                required=False,
                type=OpenApiTypes.INT,
                location="query",
            ),
        ],
        responses={200: CountrySuggestResponseSerializer},
        tags=["Geo"],
    )
    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        limit = max(1, min(50, int(request.query_params.get("limit") or 50)))

        qs = GeoPlace.objects.values("country", "country_code").distinct()
        if q:
            qs = qs.filter(country__icontains=q)

        results = [{"name": x["country"], "code": x["country_code"]} for x in qs[:limit]]
        return Response(CountrySuggestResponseSerializer({"results": results}).data)


# ---------------- Cities ----------------
class CitySuggestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [SuggestThrottle]

    @extend_schema(
        summary="Подсказки по городам",
        parameters=[
            OpenApiParameter(
                "q",
                description="Часть названия города",
                required=True,
                type=OpenApiTypes.STR,
                location="query",
            ),
            OpenApiParameter(
                "limit",
                description="Максимум результатов (1..50, по умолчанию 10)",
                required=False,
                type=OpenApiTypes.INT,
                location="query",
            ),
        ],
        responses={200: CitySuggestResponseSerializer},
        tags=["Geo"],
    )
    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        limit = max(1, min(50, int(request.query_params.get("limit") or 50)))

        if not q:
            return Response({"results": []})

        q_lower = q.lower()
        q_latin = unidecode(q).lower()

        qs = GeoPlace.objects.filter(
            Q(name__icontains=q)
            | Q(name_latin__icontains=q_lower)
            | Q(name_latin__icontains=q_latin)
        ).order_by("name")

        grouped = {}
        ordered_keys = []

        for x in qs:
            point_key = None
            if x.point:
                point_key = (round(x.point.x, 6), round(x.point.y, 6))

            dedupe_key = point_key or (x.country_code, x.name_latin.lower())

            if dedupe_key not in grouped:
                grouped[dedupe_key] = []
                ordered_keys.append(dedupe_key)

            grouped[dedupe_key].append(x)

        results = []

        for key in ordered_keys:
            variants = grouped[key]

            chosen = next((v for v in variants if is_latin(v.name)), None)
            if not chosen:
                chosen = variants[0]

            results.append(
                {
                    "name": chosen.name,
                    "country": chosen.country,
                    "country_code": chosen.country_code,
                }
            )

            if len(results) >= limit:
                break

        return Response(CitySuggestResponseSerializer({"results": results}).data)
