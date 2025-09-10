import time

import requests
from django.conf import settings
from django.contrib.gis.geos import Point

from .models import GeoPlace

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


class GeocodingError(Exception):
    pass


def geocode_city(country: str, city: str, country_code: str | None = None) -> Point:
    """
    Возвращает Point(lng, lat) для пары страна/город.
    Сначала ищет в кэше GeoPlace, затем обращается к Nominatim.
    """
    key_cc = (country_code or "").upper().strip()
    name = city.strip()
    cnt = country.strip()

    # 1) КЭШ
    qs = GeoPlace.objects.filter(name__iexact=name)
    if key_cc:
        qs = qs.filter(country_code=key_cc)
    place = qs.first()
    if place:
        return place.point

    # 2) Внешний запрос (Nominatim)
    params = {
        "city": name,
        "country": cnt,
        "format": "json",
        "limit": 1,
    }
    if key_cc:
        params["countrycodes"] = key_cc.lower()

    headers = {"User-Agent": settings.GEO_NOMINATIM_USER_AGENT}
    # простая защита от rate-limit Nominatim
    time.sleep(1.0)

    r = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=10)
    if r.status_code != 200:
        raise GeocodingError(f"Nominatim HTTP {r.status_code}")
    data = r.json()
    if not data:
        raise GeocodingError(f"City not found: {city}, {country} ({country_code})")

    rec = data[0]
    lat = float(rec["lat"])
    lon = float(rec["lon"])
    p = Point(lon, lat)

    # 3) Сохранить в кэш
    GeoPlace.objects.create(
        name=name,
        country=cnt,
        country_code=key_cc or (rec.get("address", {}).get("country_code", "")[:2].upper()),
        point=p,
        raw=rec,
    )
    return p
