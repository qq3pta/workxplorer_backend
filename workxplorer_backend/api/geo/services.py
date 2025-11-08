from __future__ import annotations

import time
import requests
from django.conf import settings
from django.contrib.gis.geos import Point

from .models import GeoPlace

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
ALLOWED_PLACE_TYPES = {"city", "town", "village", "hamlet", "locality"}
_TYPE_ORDER = {"city": 0, "town": 1, "village": 2, "hamlet": 3, "locality": 4}


class GeocodingError(Exception):
    pass


def _lang_pref(lang: str) -> str:
    """
    Accept-Language предпочтения, чтобы имена приходили на нужном языке.
    """
    lang = (lang or "ru").lower()
    if lang.startswith("uz"):
        return "uz,uz-Latn,ru,en"
    if lang.startswith("en"):
        return "en,ru,uz,uz-Latn"
    return "ru,uz,uz-Latn,en"  # default


def geocode_city(
    country: str,
    city: str,
    country_code: str | None = None,
    *,
    lang: str = "ru",
) -> Point:
    """
    Возвращает Point(lng, lat) для пары страна/город.
    1) Пытается взять из кэша GeoPlace;
    2) Иначе обращается к Nominatim, оставляя ТОЛЬКО населённые пункты.
    """
    key_cc = (country_code or "").upper().strip()
    name = (city or "").strip()
    cnt = (country or "").strip()

    if not name:
        raise GeocodingError("City is empty")

    # --- 1) КЭШ ---
    qs = GeoPlace.objects.filter(name__iexact=name)
    if key_cc:
        qs = qs.filter(country_code=key_cc)
    place = qs.first()
    if place:
        return place.point

    # --- 2) Nominatim ---
    time.sleep(1.0)  # лёгкий бэк-офф против rate limit

    params = {
        "q": name,                 # работает надёжнее, чем отдельные city/state поля
        "format": "json",
        "addressdetails": 1,
        "namedetails": 1,
        "limit": 5,
    }
    if key_cc:
        params["countrycodes"] = key_cc.lower()
    elif cnt:
        params["country"] = cnt

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
        raise GeocodingError(f"City not found: {city}, {country} ({country_code})")

    # Оставляем только населённые пункты
    candidates = []
    for rec in data:
        if rec.get("class") != "place":
            continue
        tp = rec.get("type")
        if tp not in ALLOWED_PLACE_TYPES:
            continue
        # Страна должна совпасть, если задан ISO-код
        cc = (rec.get("address", {}).get("country_code") or "").upper()
        if key_cc and cc != key_cc:
            continue
        candidates.append(rec)

    if not candidates:
        raise GeocodingError(f"City not found (filtered): {city}, {country} ({country_code})")

    # Лучшая запись: приоритет типа -> важность (по убыванию)
    candidates.sort(
        key=lambda x: (
            _TYPE_ORDER.get(x.get("type"), 99),
            -float(x.get("importance") or 0.0),
        )
    )
    rec = candidates[0]

    lat = float(rec["lat"])
    lon = float(rec["lon"])
    p = Point(lon, lat)

    # Чистое локализованное имя для кэша
    nd = rec.get("namedetails") or {}
    main_lang = lang.split(",")[0].lower()
    cache_name = (
        nd.get(f"name:{main_lang}")
        or nd.get("name:ru")
        or nd.get("name:uz")
        or nd.get("name:uz-Latn")
        or nd.get("name:en")
        or nd.get("name")
        or name
    )

    cc = (rec.get("address", {}).get("country_code") or "")[:2].upper()
    GeoPlace.objects.create(
        name=cache_name,
        country=cnt or rec.get("address", {}).get("country", "") or cc,
        country_code=key_cc or cc,
        point=p,
        raw=rec,
    )
    return p