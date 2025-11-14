from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.throttling import AnonRateThrottle
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema

from .models import GeoPlace
from .serializers import CitySuggestResponseSerializer, CountrySuggestResponseSerializer


class SuggestThrottle(AnonRateThrottle):
    rate = "60/min"


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
        limit = max(1, min(50, int(request.query_params.get("limit") or 10)))

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
        limit = max(1, min(50, int(request.query_params.get("limit") or 10)))

        if not q:
            return Response({"results": []})

        qs = GeoPlace.objects.filter(name__icontains=q)[:limit]
        results = [
            {"name": x.name, "country": x.country, "country_code": x.country_code} for x in qs
        ]

        return Response(CitySuggestResponseSerializer({"results": results}).data)
