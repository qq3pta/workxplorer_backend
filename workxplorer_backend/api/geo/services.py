from __future__ import annotations

import time
import requests
from django.conf import settings
from django.contrib.gis.geos import Point
from django.db.models import Q
from unidecode import unidecode

from .models import GeoPlace

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
ALLOWED_PLACE_TYPES = {"city", "town", "village", "hamlet", "locality"}
_TYPE_ORDER = {"city": 0, "town": 1, "village": 2, "hamlet": 3, "locality": 4}


class GeocodingError(Exception):
    pass


def _lang_pref(lang: str) -> str:
    lang = (lang or "ru").lower()
    if lang.startswith("uz"):
        return "uz,uz-Latn,ru,en"
    if lang.startswith("en"):
        return "en,ru,uz,uz-Latn"
    return "ru,uz,uz-Latn,en"


def geocode_city(
    country: str,
    city: str,
    country_code: str | None = None,
    *,
    lang: str = "ru",
) -> Point:
    """
    1) Поиск в GeoPlace по:
        - name (Москва)
        - name_latin (moskva, moscow)
        - unidecode(city)
    2) Если нет — запрос к Nominatim → сохранение в GeoPlace
    """
    key_cc = (country_code or "").upper().strip()
    city_raw = (city or "").strip()
    country_raw = (country or "").strip()

    if not city_raw:
        raise GeocodingError("City is empty")

    city_norm = city_raw.lower()
    city_latin = unidecode(city_norm).lower()

    qs = GeoPlace.objects.filter(
        Q(name__iexact=city_norm)
        | Q(name_latin__iexact=city_norm)
        | Q(name_latin__iexact=city_latin)
        | Q(name__icontains=city_norm)
        | Q(name_latin__icontains=city_norm)
        | Q(name_latin__icontains=city_latin)
    )

    if key_cc:
        qs = qs.filter(country_code=key_cc)

    place = qs.first()
    if place and place.point:
        return place.point

    time.sleep(1.0)

    params = {
        "q": city_raw,
        "format": "json",
        "addressdetails": 1,
        "namedetails": 1,
        "limit": 5,
    }
    if key_cc:
        params["countrycodes"] = key_cc.lower()
    elif country_raw:
        params["country"] = country_raw

    headers = {
        "User-Agent": getattr(settings, "GEO_NOMINATIM_USER_AGENT", "workxplorer/geo-geocode"),
        "Accept-Language": _lang_pref(lang),
    }

    try:
        r = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        raise GeocodingError(f"Nominatim error: {e}") from e

    if not isinstance(data, list) or not data:
        raise GeocodingError(f"City not found: {city_raw}, {country_raw} ({country_code})")

    candidates = []
    for rec in data:
        if rec.get("class") != "place":
            continue
        tp = rec.get("type")
        if tp not in ALLOWED_PLACE_TYPES:
            continue

        cc = (rec.get("address", {}).get("country_code") or "").upper()
        if key_cc and cc != key_cc:
            continue

        candidates.append(rec)

    if not candidates:
        raise GeocodingError(
            f"City not found (filtered): {city_raw}, {country_raw} ({country_code})"
        )

    candidates.sort(
        key=lambda x: (_TYPE_ORDER.get(x.get("type"), 99), -float(x.get("importance") or 0.0))
    )

    rec = candidates[0]

    lat = float(rec["lat"])
    lon = float(rec["lon"])
    point = Point(lon, lat)

    nd = rec.get("namedetails") or {}
    main_lang = lang.split(",")[0].lower()

    cache_name = (
        nd.get(f"name:{main_lang}")
        or nd.get("name:ru")
        or nd.get("name:uz")
        or nd.get("name:uz-Latn")
        or nd.get("name:en")
        or nd.get("name")
        or city_raw
    )

    cc = (rec.get("address", {}).get("country_code") or "")[:2].upper()

    GeoPlace.objects.create(
        name=cache_name,
        name_latin=unidecode(cache_name).lower(),
        country=country_raw or rec.get("address", {}).get("country", "") or cc,
        country_code=key_cc or cc,
        point=point,
        raw=rec,
    )

    return point
