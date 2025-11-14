from __future__ import annotations

from typing import Literal

import requests
from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema

from .serializers import CitySuggestResponseSerializer, CountrySuggestResponseSerializer

# --- Страны ---
ISO_COUNTRIES = [
    {"code": "KZ", "name": "Казахстан"},
    {"code": "UZ", "name": "Узбекистан"},
    {"code": "KG", "name": "Киргизия"},
    {"code": "TJ", "name": "Таджикистан"},
    {"code": "TM", "name": "Туркменистан"},
    {"code": "CN", "name": "Китай"},
    {"code": "MN", "name": "Монголия"},
    {"code": "AF", "name": "Афганистан"},
    {"code": "PK", "name": "Пакистан"},
    {"code": "IN", "name": "Индия"},
    {"code": "AZ", "name": "Азербайджан"},
    {"code": "AM", "name": "Армения"},
    {"code": "GE", "name": "Грузия"},
    {"code": "TR", "name": "Турция"},
    {"code": "IR", "name": "Иран"},
    {"code": "RU", "name": "Россия"},
    {"code": "BY", "name": "Беларусь"},
    {"code": "UA", "name": "Украина"},
    {"code": "PL", "name": "Польша"},
    {"code": "HU", "name": "Венгрия"},
    {"code": "RO", "name": "Румыния"},
    {"code": "BG", "name": "Болгария"},
    {"code": "RS", "name": "Сербия"},
    {"code": "GR", "name": "Греция"},
]

ALLOWED_COUNTRY_CODES = {c["code"] for c in ISO_COUNTRIES}
ALLOWED_PLACE_TYPES = {"city", "town", "village", "hamlet", "locality"}


class SuggestThrottle(AnonRateThrottle):
    rate = "60/min"


def _lang_pref(lang: str) -> str:
    lang = (lang or "ru").lower()
    if lang.startswith("uz"):
        return "uz,uz-Latn,ru,en"
    if lang.startswith("en"):
        return "en,ru,uz,uz-Latn"
    return "ru,uz,uz-Latn,en"


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
                location=Literal["query"],
            ),
            OpenApiParameter(
                "limit",
                description="Максимум результатов (1..50, по умолчанию 10)",
                required=False,
                type=OpenApiTypes.INT,
                location=Literal["query"],
            ),
        ],
        responses={200: CountrySuggestResponseSerializer},
        tags=["Geo"],
    )
    def get(self, request):
        q = (request.query_params.get("q") or "").strip().lower()
        try:
            limit = int(request.query_params.get("limit") or 10)
        except ValueError:
            limit = 10
        limit = max(1, min(50, limit))

        results = (
            [c for c in ISO_COUNTRIES if q in c["name"].lower() or q in c["code"].lower()]
            if q
            else ISO_COUNTRIES
        )

        return Response({"results": results[:limit]})


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
                location=Literal["query"],
            ),
            OpenApiParameter(
                "country",
                description="ISO-2 код страны для фильтра (необязательно)",
                required=False,
                type=OpenApiTypes.STR,
                location=Literal["query"],
            ),
            OpenApiParameter(
                "lang",
                description="Язык результата: ru | uz | en (по умолчанию ru)",
                required=False,
                type=OpenApiTypes.STR,
                location=Literal["query"],
            ),
            OpenApiParameter(
                "limit",
                description="Максимум результатов (1..50, по умолчанию 10)",
                required=False,
                type=OpenApiTypes.INT,
                location=Literal["query"],
            ),
        ],
        responses={200: CitySuggestResponseSerializer},
        tags=["Geo"],
    )
    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        country = (request.query_params.get("country") or "").upper().strip()
        lang = (request.query_params.get("lang") or "ru").strip()
        try:
            limit = int(request.query_params.get("limit") or 10)
        except ValueError:
            limit = 10
        limit = max(1, min(50, limit))

        if len(q) < 2 or (country and country not in ALLOWED_COUNTRY_CODES):
            return Response({"results": []})

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
            r = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params=params,
                headers=headers,
                timeout=8,
            )
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list):
                data = []

            out, seen = [], set()
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
                out.append({"name": name, "country": country_label, "country_code": cc})

                if len(out) >= limit:
                    break

            return Response({"results": out})
        except requests.RequestException:
            return Response({"results": []})
