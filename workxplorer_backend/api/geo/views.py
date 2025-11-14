from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.throttling import AnonRateThrottle
from django.db.models import Q

from .models import GeoPlace
from .serializers import CitySuggestResponseSerializer, CountrySuggestResponseSerializer


class SuggestThrottle(AnonRateThrottle):
    rate = "60/min"


# ---------------- Countries ----------------
class CountrySuggestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [SuggestThrottle]

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        limit = max(1, min(50, int(request.query_params.get("limit") or 10)))

        qs = GeoPlace.objects.values("country", "country_code").distinct()
        if q:
            qs = qs.filter(Q(country__icontains=q) | Q(country_code__icontains=q))

        results = [{"name": x["country"], "code": x["country_code"]} for x in qs[:limit]]

        serializer = CountrySuggestResponseSerializer({"results": results})
        return Response(serializer.data)


# ---------------- Cities ----------------
class CitySuggestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [SuggestThrottle]

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        country = (request.query_params.get("country") or "").upper().strip()
        limit = max(1, min(50, int(request.query_params.get("limit") or 10)))

        if len(q) < 2:
            return Response({"results": []})

        qs = GeoPlace.objects.all()
        if country:
            qs = qs.filter(country_code__iexact=country)
        qs = qs.filter(name__icontains=q)[:limit]

        results = [
            {"name": x.name, "country": x.country, "country_code": x.country_code} for x in qs
        ]
        serializer = CitySuggestResponseSerializer({"results": results})
        return Response(serializer.data)
