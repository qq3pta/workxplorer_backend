import requests
from django.conf import settings
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from .serializers import CountrySuggestResponseSerializer, CitySuggestResponseSerializer

# Список стран
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
    """Цепочка Accept-Language."""
    lang = (lang or "ru").lower()
    if lang.startswith("uz"):
        return "uz,uz-Latn,ru,en"
    if lang.startswith("en"):
        return "en,ru,uz,uz-Latn"
    return "ru,uz,uz-Latn,en"


class CountrySuggestView(APIView):
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
            ),
            OpenApiParameter(
                name="limit",
                description="Максимум результатов (1..50, по умолчанию 10)",
                required=False,
                type=OpenApiTypes.INT,
            ),
        ],
        responses={200: CountrySuggestResponseSerializer},
        tags=["Geo"],
    )
    def get(self, request):
        q = (request.query_params.get("q") or "").strip().lower()
        limit = max(1, min(50, int(request.query_params.get("limit") or 10)))

        if not q:
            data = ISO_COUNTRIES[:limit]
        else:
            # фильтр по названию или коду
            data = [c for c in ISO_COUNTRIES if q in c["name"].lower() or q in c["code"].lower()][
                :limit
            ]
        return Response({"results": data})


class CitySuggestView(APIView):
    """
    Подсказки по городам через Nominatim (OpenStreetMap) с приоритетом совпадений в начале имени.
    """

    permission_classes = [AllowAny]
    throttle_classes = [SuggestThrottle]

    @extend_schema(
        summary="Подсказки по городам (сортировка по совпадению в начале)",
        parameters=[
            OpenApiParameter(
                name="q",
                description="Строка поиска (мин 2 символа)",
                required=True,
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name="country",
                description="ISO-2 код страны",
                required=False,
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name="lang", description="Язык: ru|uz|en", required=False, type=OpenApiTypes.STR
            ),
            OpenApiParameter(
                name="limit",
                description="Максимум результатов (1..50)",
                required=False,
                type=OpenApiTypes.INT,
            ),
        ],
        responses={200: CitySuggestResponseSerializer},
        tags=["Geo"],
    )
    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if len(q) < 2:
            return Response({"results": []})

        country = (request.query_params.get("country") or "").upper().strip()
        if country and country not in ALLOWED_COUNTRY_CODES:
            return Response({"results": []})

        lang = (request.query_params.get("lang") or "ru").strip()
        limit = max(1, min(50, int(request.query_params.get("limit") or 10)))

        try:
            params = {
                "q": q,
                "format": "json",
                "addressdetails": 1,
                "namedetails": 1,
                "limit": limit * 3,  # берём больше, чтобы фильтровать и сортировать
                "countrycodes": country.lower()
                if country
                else ",".join(cc.lower() for cc in ALLOWED_COUNTRY_CODES),
            }
            headers = {
                "User-Agent": getattr(
                    settings, "GEO_NOMINATIM_USER_AGENT", "workxplorer/geo-suggest"
                ),
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

            seen = set()
            start_matches, inside_matches = [], []
            q_lower = q.lower()

            for item in data:
                if item.get("class") != "place" or item.get("type") not in ALLOWED_PLACE_TYPES:
                    continue

                addr = item.get("address") or {}
                cc = (addr.get("country_code") or "").upper()
                if cc not in ALLOWED_COUNTRY_CODES:
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
                name = next((v for v in candidates if v), None)
                if not name or q_lower not in name.lower():
                    continue

                key = (name, cc)
                if key in seen:
                    continue
                seen.add(key)

                country_label = addr.get("country") or cc
                city_obj = {"name": name, "country": country_label, "country_code": cc}

                # Сортировка: сначала начало совпадения
                if name.lower().startswith(q_lower):
                    start_matches.append(city_obj)
                else:
                    inside_matches.append(city_obj)

            out = start_matches + inside_matches
            return Response({"results": out[:limit]})

        except Exception:
            return Response({"results": []})
