from __future__ import annotations

import time

import requests
from django.conf import settings
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.throttling import AnonRateThrottle
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema

from .models import GeoPlace
from .serializers import CitySuggestResponseSerializer, CountrySuggestResponseSerializer

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
ALLOWED_PLACE_TYPES = {"city", "town", "village", "hamlet", "locality"}
_TYPE_ORDER = {"city": 0, "town": 1, "village": 2, "hamlet": 3, "locality": 4}


class SuggestThrottle(AnonRateThrottle):
    rate = "60/min"


def _lang_pref(lang: str) -> str:
    lang = (lang or "ru").lower()
    if lang.startswith("uz"):
        return "uz,uz-Latn,ru,en"
    if lang.startswith("en"):
        return "en,ru,uz,uz-Latn"
    return "ru,uz,uz-Latn,en"


def _search_nominatim_city(q: str, country: str | None, lang: str, limit: int = 10):
    """
    Поиск города через Nominatim с фильтром по стране и локализацией.
    """
    params = {
        "q": q,
        "format": "json",
        "addressdetails": 1,
        "namedetails": 1,
        "limit": limit,
    }
    if country:
        params["countrycodes"] = country.lower()

    headers = {
        "User-Agent": getattr(settings, "GEO_NOMINATIM_USER_AGENT", "workxplorer/geo-suggest"),
        "Accept-Language": _lang_pref(lang),
    }

    try:
        time.sleep(1)  # rate limit
        r = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=8)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            return []
        return data
    except requests.RequestException:
        return []


# ---------------- Countries ----------------
class CountrySuggestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [SuggestThrottle]

    @extend_schema(
        summary="Подсказки по странам",
        parameters=[
            OpenApiParameter(
                "q",
                description="Код страны (ISO-2) или часть названия",
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
            qs = qs.filter(Q(country__icontains=q) | Q(country_code__icontains=q))

        results = [{"name": x["country"], "code": x["country_code"]} for x in qs[:limit]]
        serializer = CountrySuggestResponseSerializer({"results": results})
        return Response(serializer.data)


# ---------------- Cities ----------------
class CitySuggestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [SuggestThrottle]

    @extend_schema(
        summary="Подсказки по городам",
        parameters=[
            OpenApiParameter(
                "q",
                description="Строка поиска (минимум 2 символа)",
                required=True,
                type=OpenApiTypes.STR,
                location="query",
            ),
            OpenApiParameter(
                "country",
                description="ISO-2 код страны для фильтра (необязательно)",
                required=False,
                type=OpenApiTypes.STR,
                location="query",
            ),
            OpenApiParameter(
                "lang",
                description="Язык результата: ru | uz | en (по умолчанию ru)",
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
        responses={200: CitySuggestResponseSerializer},
        tags=["Geo"],
    )
    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        country = (request.query_params.get("country") or "").upper().strip()
        lang = (request.query_params.get("lang") or "ru").strip()
        limit = max(1, min(50, int(request.query_params.get("limit") or 10)))

        if len(q) < 2:
            return Response({"results": []})

        # Сначала поиск в GeoPlace
        qs = GeoPlace.objects.all()
        if country:
            qs = qs.filter(country_code__iexact=country)
        qs = qs.filter(name__icontains=q)[:limit]

        results = [
            {"name": x.name, "country": x.country, "country_code": x.country_code} for x in qs
        ]

        # Если ничего не найдено — обращаемся к Nominatim
        if not results:
            data = _search_nominatim_city(q, country, lang, limit)
            seen = set()
            for item in data:
                if item.get("class") != "place" or item.get("type") not in ALLOWED_PLACE_TYPES:
                    continue
                cc = (item.get("address", {}).get("country_code") or "").upper()
                name_candidates = [
                    item.get("namedetails", {}).get(f"name:{lang}"),
                    item.get("namedetails", {}).get("name:ru"),
                    item.get("namedetails", {}).get("name:uz-Latn"),
                    item.get("namedetails", {}).get("name:uz"),
                    item.get("namedetails", {}).get("name:en"),
                    (item.get("display_name") or "").split(",")[0].strip(),
                ]
                name = next((n for n in name_candidates if n), None)
                if not name or (name, cc) in seen:
                    continue
                seen.add((name, cc))
                country_label = item.get("address", {}).get("country") or cc

                # Сохраняем в GeoPlace
                try:
                    GeoPlace.objects.create(
                        name=name,
                        country=country_label,
                        country_code=cc,
                        point=None,
                        provider="nominatim",
                        raw=item,
                    )
                except Exception:
                    pass

                results.append({"name": name, "country": country_label, "country_code": cc})
                if len(results) >= limit:
                    break

        serializer = CitySuggestResponseSerializer({"results": results[:limit]})
        return Response(serializer.data)
