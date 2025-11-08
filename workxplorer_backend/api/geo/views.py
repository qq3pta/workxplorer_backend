import requests
from django.conf import settings
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from .serializers import (
    CitySuggestResponseSerializer,
    CountrySuggestResponseSerializer,
)

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
    """
    Accept-Language цепочка предпочтений.
    """
    lang = (lang or "ru").lower()
    if lang.startswith("uz"):
        return "uz,uz-Latn,ru,en"
    if lang.startswith("en"):
        return "en,ru,uz,uz-Latn"
    return "ru,uz,uz-Latn,en"  # default


class CountrySuggestView(APIView):
    """
    Подсказки по странам из предзаданного списка ISO_COUNTRIES.
    """

    permission_classes = [AllowAny]
    throttle_classes = [SuggestThrottle]

    @extend_schema(
        summary="Подсказки по странам",
        parameters=[
            OpenApiParameter(
                name="q",
                description="Код страны (ISO-2) или часть названия",
                required=False,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name="limit",
                description="Максимум результатов (1..50, по умолчанию 10)",
                required=False,
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
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

        if not q:
            data = ISO_COUNTRIES[:limit]
        else:
            data = [c for c in ISO_COUNTRIES if q in c["name"].lower() or q in c["code"].lower()][
                :limit
            ]
        return Response({"results": data})


class CitySuggestView(APIView):
    """
    Подсказки по городам через Nominatim (OpenStreetMap), ограниченные списком ALLOWED_COUNTRY_CODES.
    Возвращает ТОЛЬКО населённые пункты (без улиц/площадей), локализованные под язык.
    """

    permission_classes = [AllowAny]
    throttle_classes = [SuggestThrottle]

    @extend_schema(
        summary="Подсказки по городам",
        parameters=[
            OpenApiParameter(
                name="q",
                description="Строка поиска (минимум 2 символа)",
                required=True,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name="country",
                description="ISO-2 код страны для фильтра (необязательно). Допустимые: "
                + ", ".join(sorted(ALLOWED_COUNTRY_CODES)),
                required=False,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name="lang",
                description="Язык результата: ru | uz | en (по умолчанию ru)",
                required=False,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
            ),
            OpenApiParameter(
                name="limit",
                description="Максимум результатов (1..50, по умолчанию 10)",
                required=False,
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
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

        if len(q) < 2:
            return Response({"results": []})
        if country and country not in ALLOWED_COUNTRY_CODES:
            return Response({"results": []})

        try:
            params = {
                "q": q,
                "format": "json",
                "addressdetails": 1,
                "namedetails": 1,  # чтобы взять «чистое» имя
                "limit": limit,
                "countrycodes": (
                    country.lower()
                    if country
                    else ",".join(code.lower() for code in ALLOWED_COUNTRY_CODES)
                ),
            }

            ua = getattr(settings, "GEO_NOMINATIM_USER_AGENT", "workxplorer/geo-suggest")
            headers = {
                "User-Agent": ua,
                "Accept-Language": _lang_pref(lang),
            }

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
                # только населённые пункты
                if item.get("class") != "place" or item.get("type") not in ALLOWED_PLACE_TYPES:
                    continue

                addr = item.get("address") or {}
                cc = (addr.get("country_code") or "").upper()
                if not cc or cc not in ALLOWED_COUNTRY_CODES:
                    continue

                nd = item.get("namedetails") or {}
                main_lang = lang.split(",")[0]
                candidates = [
                    nd.get(f"name:{main_lang}"),
                    nd.get("name:ru"),
                    nd.get("name:uz"),
                    nd.get("name:uz-Latn"),
                    nd.get("name:en"),
                    nd.get("name"),
                ]
                name = next((v for v in candidates if v), None) or (
                    (item.get("display_name") or "").split(",")[0].strip()
                )
                if not name:
                    continue

                country_label = addr.get("country") or cc

                key = (name, cc)
                if key in seen:
                    continue
                seen.add(key)

                out.append({"name": name, "country": country_label, "country_code": cc})
                if len(out) >= limit:
                    break

            return Response({"results": out})
        except Exception:
            return Response({"results": []})
