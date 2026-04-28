from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from unidecode import unidecode

from .models import GeoPlace
from .serializers import (
    CitySuggestResponseSerializer,
    CountrySuggestResponseSerializer,
    RegionSuggestResponseSerializer,
)


class SuggestThrottle(AnonRateThrottle):
    rate = "60/min"


COUNTRY_DISPLAY_MAP = {
    "Казахстан": {"ru": "Казахстан", "en": "Kazakhstan", "uz": "Kazakhstan"},
    "Kazakhstan": {"ru": "Казахстан", "en": "Kazakhstan", "uz": "Kazakhstan"},
    "Узбекистан": {"ru": "Узбекистан", "en": "Uzbekistan", "uz": "Uzbekistan"},
    "Uzbekistan": {"ru": "Узбекистан", "en": "Uzbekistan", "uz": "Uzbekistan"},
    "Киргизия": {"ru": "Киргизия", "en": "Kyrgyzstan", "uz": "Kyrgyzstan"},
    "Кыргызстан": {"ru": "Киргизия", "en": "Kyrgyzstan", "uz": "Kyrgyzstan"},
    "Kyrgyzstan": {"ru": "Киргизия", "en": "Kyrgyzstan", "uz": "Kyrgyzstan"},
    "Таджикистан": {"ru": "Таджикистан", "en": "Tajikistan", "uz": "Tajikistan"},
    "Tajikistan": {"ru": "Таджикистан", "en": "Tajikistan", "uz": "Tajikistan"},
    "Туркменистан": {"ru": "Туркменистан", "en": "Turkmenistan", "uz": "Turkmenistan"},
    "Turkmenistan": {"ru": "Туркменистан", "en": "Turkmenistan", "uz": "Turkmenistan"},
    "Китай": {"ru": "Китай", "en": "China", "uz": "China"},
    "China": {"ru": "Китай", "en": "China", "uz": "China"},
    "Монголия": {"ru": "Монголия", "en": "Mongolia", "uz": "Mongolia"},
    "Mongolia": {"ru": "Монголия", "en": "Mongolia", "uz": "Mongolia"},
    "Афганистан": {"ru": "Афганистан", "en": "Afghanistan", "uz": "Afghanistan"},
    "Afghanistan": {"ru": "Афганистан", "en": "Afghanistan", "uz": "Afghanistan"},
    "Пакистан": {"ru": "Пакистан", "en": "Pakistan", "uz": "Pakistan"},
    "Pakistan": {"ru": "Пакистан", "en": "Pakistan", "uz": "Pakistan"},
    "Индия": {"ru": "Индия", "en": "India", "uz": "India"},
    "India": {"ru": "Индия", "en": "India", "uz": "India"},
    "Азербайджан": {"ru": "Азербайджан", "en": "Azerbaijan", "uz": "Azerbaijan"},
    "Azerbaijan": {"ru": "Азербайджан", "en": "Azerbaijan", "uz": "Azerbaijan"},
    "Армения": {"ru": "Армения", "en": "Armenia", "uz": "Armenia"},
    "Armenia": {"ru": "Армения", "en": "Armenia", "uz": "Armenia"},
    "Грузия": {"ru": "Грузия", "en": "Georgia", "uz": "Georgia"},
    "Georgia": {"ru": "Грузия", "en": "Georgia", "uz": "Georgia"},
    "Турция": {"ru": "Турция", "en": "Turkey", "uz": "Turkey"},
    "Turkey": {"ru": "Турция", "en": "Turkey", "uz": "Turkey"},
    "Иран": {"ru": "Иран", "en": "Iran", "uz": "Iran"},
    "Iran": {"ru": "Иран", "en": "Iran", "uz": "Iran"},
    "Россия": {"ru": "Россия", "en": "Russia", "uz": "Russia"},
    "Russia": {"ru": "Россия", "en": "Russia", "uz": "Russia"},
    "Беларусь": {"ru": "Беларусь", "en": "Belarus", "uz": "Belarus"},
    "Belarus": {"ru": "Беларусь", "en": "Belarus", "uz": "Belarus"},
    "Украина": {"ru": "Украина", "en": "Ukraine", "uz": "Ukraine"},
    "Ukraine": {"ru": "Украина", "en": "Ukraine", "uz": "Ukraine"},
    "Польша": {"ru": "Польша", "en": "Poland", "uz": "Poland"},
    "Poland": {"ru": "Польша", "en": "Poland", "uz": "Poland"},
    "Венгрия": {"ru": "Венгрия", "en": "Hungary", "uz": "Hungary"},
    "Hungary": {"ru": "Венгрия", "en": "Hungary", "uz": "Hungary"},
    "Румыния": {"ru": "Румыния", "en": "Romania", "uz": "Romania"},
    "Romania": {"ru": "Румыния", "en": "Romania", "uz": "Romania"},
    "Болгария": {"ru": "Болгария", "en": "Bulgaria", "uz": "Bulgaria"},
    "Bulgaria": {"ru": "Болгария", "en": "Bulgaria", "uz": "Bulgaria"},
    "Сербия": {"ru": "Сербия", "en": "Serbia", "uz": "Serbia"},
    "Serbia": {"ru": "Сербия", "en": "Serbia", "uz": "Serbia"},
    "Греция": {"ru": "Греция", "en": "Greece", "uz": "Greece"},
    "Greece": {"ru": "Греция", "en": "Greece", "uz": "Greece"},
}


def get_lang(request) -> str:
    lang = (request.query_params.get("lang") or "ru").strip().lower()
    if lang not in {"ru", "en", "uz"}:
        return "ru"
    return lang


def normalize_country(country: str, lang: str) -> str:
    data = COUNTRY_DISPLAY_MAP.get((country or "").strip())
    if not data:
        return (country or "").strip()
    return data.get(lang, data["ru"])


def is_cyrillic(text: str) -> bool:
    return any("А" <= ch <= "я" or ch in "ЁёЎўҚқҒғҲҳ" for ch in text)


def pick_city_variant(variants, lang: str):
    if lang == "ru":
        return next((v for v in variants if is_cyrillic(v.name)), None)
    else:
        return next((v for v in variants if not is_cyrillic(v.name)), None)


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
                "country_code",
                description="ISO-2 код страны, например UZ, KZ",
                required=False,
                type=OpenApiTypes.STR,
                location="query",
            ),
            OpenApiParameter(
                "limit",
                description="Максимум результатов (1..50, по умолчанию 50)",
                required=False,
                type=OpenApiTypes.INT,
                location="query",
            ),
            OpenApiParameter(
                "lang",
                description="Язык интерфейса: ru/en/uz",
                required=False,
                type=OpenApiTypes.STR,
                location="query",
            ),
        ],
        responses={200: CountrySuggestResponseSerializer},
        tags=["Geo"],
    )
    def get(self, request):
        q = (request.query_params.get("q") or "").strip().lower()
        limit = max(1, min(50, int(request.query_params.get("limit") or 50)))
        country_code = (request.query_params.get("country_code") or "").strip().upper()
        lang = get_lang(request)

        qs = GeoPlace.objects.exclude(country__isnull=True).exclude(country="")

        if country_code:
            qs = qs.filter(country_code=country_code)

        raw_countries = qs.values_list("country", flat=True).distinct().order_by("country")

        seen = set()
        results = []

        for raw_country in raw_countries:
            display_name = normalize_country(raw_country, lang)

            if q and q not in raw_country.lower() and q not in display_name.lower():
                continue

            key = display_name.lower()
            if key in seen:
                continue
            seen.add(key)

            results.append({"name": display_name})

            if len(results) >= limit:
                break

        return Response(CountrySuggestResponseSerializer({"results": results}).data)


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
            OpenApiParameter(
                "lang",
                description="Язык интерфейса: ru/en/uz",
                required=False,
                type=OpenApiTypes.STR,
                location="query",
            ),
        ],
        responses={200: CitySuggestResponseSerializer},
        tags=["Geo"],
    )
    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        limit = max(1, min(50, int(request.query_params.get("limit") or 50)))
        lang = get_lang(request)

        if not q:
            return Response({"results": []})

        q_lower = q.lower()
        q_latin = unidecode(q).lower()

        if lang == "ru":
            qs = GeoPlace.objects.filter(Q(name__icontains=q) | Q(country__icontains=q)).order_by(
                "name"
            )
        else:
            qs = GeoPlace.objects.filter(
                Q(name_latin__icontains=q_lower) | Q(name_latin__icontains=q_latin)
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
            chosen = pick_city_variant(variants, lang)

            if not chosen:
                continue

            results.append(
                {
                    "name": chosen.name,
                    "country": normalize_country(chosen.country, lang),
                    "country_code": chosen.country_code,
                }
            )

            if len(results) >= limit:
                break

        return Response(CitySuggestResponseSerializer({"results": results}).data)


class RegionSuggestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [SuggestThrottle]

    @extend_schema(
        summary="Подсказки по регионам",
        parameters=[
            OpenApiParameter(
                "q",
                description="Часть названия региона",
                required=False,
                type=OpenApiTypes.STR,
                location="query",
            ),
            OpenApiParameter(
                "country_code",
                description="ISO-2 код страны, например UZ, KZ",
                required=False,
                type=OpenApiTypes.STR,
                location="query",
            ),
            OpenApiParameter(
                "limit",
                description="Максимум результатов (1..50, по умолчанию 50)",
                required=False,
                type=OpenApiTypes.INT,
                location="query",
            ),
        ],
        responses={200: RegionSuggestResponseSerializer},
        tags=["Geo"],
    )
    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        limit = max(1, min(50, int(request.query_params.get("limit") or 50)))
        country_code = (request.query_params.get("country_code") or "").strip().upper()

        qs = GeoPlace.objects.exclude(region__isnull=True).exclude(region="")

        if country_code:
            qs = qs.filter(country_code=country_code)

        if q:
            qs = qs.filter(region__icontains=q)

        regions = qs.values_list("region", flat=True).distinct().order_by("region")[:limit]

        return Response(
            RegionSuggestResponseSerializer({"results": [{"name": r} for r in regions]}).data
        )


@extend_schema(tags=["Geo"])
class MapCountriesView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        lang = get_lang(request)

        rows = (
            GeoPlace.objects.exclude(country__isnull=True)
            .exclude(country="")
            .values("country", "country_code")
            .distinct()
            .order_by("country")
        )

        seen = set()
        results = []

        for row in rows:
            country_name = normalize_country(row["country"], lang)
            key = row["country_code"]

            if key in seen:
                continue

            seen.add(key)

            results.append(
                {
                    "name": country_name,
                    "country_code": row["country_code"],
                }
            )

        return Response({"results": results})


@extend_schema(tags=["Geo"])
class MapRegionsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        country_code = (request.query_params.get("country_code") or "").strip().upper()

        if not country_code:
            return Response({"detail": "country_code is required"}, status=400)

        regions = (
            GeoPlace.objects.filter(country_code=country_code)
            .exclude(region__isnull=True)
            .exclude(region="")
            .values_list("region", flat=True)
            .distinct()
            .order_by("region")
        )

        return Response({"results": [{"name": region} for region in regions]})


@extend_schema(tags=["Geo"])
class MapCitiesView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        country_code = (request.query_params.get("country_code") or "").strip().upper()
        region = (request.query_params.get("region") or "").strip()
        lang = get_lang(request)

        if not country_code:
            return Response({"detail": "country_code is required"}, status=400)

        qs = GeoPlace.objects.filter(
            country_code=country_code,
            region__iexact=region,
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
            chosen = pick_city_variant(grouped[key], lang)

            if not chosen:
                continue

            results.append({"name": chosen.name, "region": chosen.region})

        return Response({"results": results})
