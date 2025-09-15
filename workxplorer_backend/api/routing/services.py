from __future__ import annotations

import hashlib
import os
from datetime import timedelta
from typing import Optional, Tuple

import requests
from django.contrib.gis.geos import Point
from django.utils.timezone import now
from django.db.utils import OperationalError, ProgrammingError

from .models import RouteCache

"""
Routing (ORS-only, GET-first)

ENV:
  ROUTE_PROVIDER=ors
  ORS_API_KEY=<твой ey... или hex 5b3ce...>
  ORS_BASE_URL=https://api.openrouteservice.org
  ROUTING_HTTP_TIMEOUT=15
  ROUTING_CACHE_TTL_HOURS=720
  ROUTING_DEBUG=1
"""

ORS_API_KEY   = (os.getenv("ORS_API_KEY") or "").strip()
ORS_BASE      = (os.getenv("ORS_BASE_URL") or "https://api.openrouteservice.org").strip()
HTTP_TIMEOUT  = float(os.getenv("ROUTING_HTTP_TIMEOUT", "15"))
CACHE_TTL_HOURS_DEFAULT = int(os.getenv("ROUTING_CACHE_TTL_HOURS", str(24 * 30)))
ROUTING_DEBUG = os.getenv("ROUTING_DEBUG") == "1"


class RoutingUnavailable(Exception):
    pass


def _norm(pt: Point, nd: int = 3) -> str:
    return f"{round(pt.y, nd):.{nd}f},{round(pt.x, nd):.{nd}f}"


def _cache_key(p1: Point, p2: Point, nd: int = 3) -> str:
    raw = f"{_norm(p1, nd)}|{_norm(p2, nd)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _parse_ors(data: dict) -> Tuple[float, float]:
    # Ожидаем GeoJSON с features[].properties.summary.{distance,duration}
    if not isinstance(data, dict) or "features" not in data:
        raise RoutingUnavailable(f"ORS unexpected response: {data}")
    feats = data.get("features") or []
    if not feats:
        raise RoutingUnavailable("ORS returned no features")
    summ = (feats[0].get("properties") or {}).get("summary") or {}
    dist_m = summ.get("distance") or 0
    dur_s  = summ.get("duration") or 0
    if not dist_m:
        raise RoutingUnavailable(f"ORS no distance in summary: {feats[0].get('properties')}")
    return dist_m / 1000.0, dur_s / 60.0


def _route_ors(p1: Point, p2: Point) -> Tuple[float, float, dict, str]:
    if not ORS_API_KEY:
        raise RoutingUnavailable("ORS key missing")

    base = ORS_BASE.rstrip("/")
    url_post = f"{base}/v2/directions/driving-car"

    # 1) GET (минимальный, разрешён твоим токеном): ?api_key=&start=lon,lat&end=lon,lat
    try:
        params = {
            "api_key": ORS_API_KEY,
            "start": f"{p1.x},{p1.y}",
            "end": f"{p2.x},{p2.y}",
        }
        r = requests.get(url_post, params=params, timeout=HTTP_TIMEOUT)
        if ROUTING_DEBUG:
            ct = r.headers.get("content-type", "")
            body = r.text if "json" not in ct.lower() else r.json()
            print(f"[routing] ORS GET status={r.status_code} body_snippet={str(body)[:200]}")
        r.raise_for_status()
        data = r.json()
        km, minutes = _parse_ors(data)
        return km, minutes, data, "ors"
    except Exception as e:
        if ROUTING_DEBUG:
            print(f"[routing] ORS GET failed: {repr(e)}")

    # 2) POST Bearer (для ey...)
    try:
        headers = {"Content-Type": "application/json"}
        if ORS_API_KEY.startswith(("eyJ", "ey", "eyJ0")):
            headers["Authorization"] = f"Bearer {ORS_API_KEY}"
        else:
            headers["Authorization"] = ORS_API_KEY
        payload = {"coordinates": [[p1.x, p1.y], [p2.x, p2.y]], "instructions": False}
        r = requests.post(url_post, json=payload, headers=headers, timeout=HTTP_TIMEOUT)
        if ROUTING_DEBUG:
            ct = r.headers.get("content-type", "")
            body = r.text if "json" not in ct.lower() else r.json()
            print(f"[routing] ORS POST hdr status={r.status_code} body_snippet={str(body)[:200]}")
        r.raise_for_status()
        data = r.json()
        km, minutes = _parse_ors(data)
        return km, minutes, data, "ors"
    except Exception as e:
        if ROUTING_DEBUG:
            print(f"[routing] ORS POST-hdr failed: {repr(e)}")

    # 3) POST ?api_key=...
    try:
        payload = {"coordinates": [[p1.x, p1.y], [p2.x, p2.y]], "instructions": False}
        r = requests.post(url_post, params={"api_key": ORS_API_KEY},
                          json=payload, headers={"Content-Type": "application/json"},
                          timeout=HTTP_TIMEOUT)
        if ROUTING_DEBUG:
            ct = r.headers.get("content-type", "")
            body = r.text if "json" not in ct.lower() else r.json()
            print(f"[routing] ORS POST query status={r.status_code} body_snippet={str(body)[:200]}")
        r.raise_for_status()
        data = r.json()
        km, minutes = _parse_ors(data)
        return km, minutes, data, "ors"
    except Exception as e:
        if ROUTING_DEBUG:
            print(f"[routing] ORS POST-query failed: {repr(e)}")

    raise RoutingUnavailable("ORS failed for all strategies")


def get_route(
    p1: Optional[Point],
    p2: Optional[Point],
    ttl_hours: int = CACHE_TTL_HOURS_DEFAULT,
) -> Optional[RouteCache]:
    if not (p1 and p2):
        return None

    key = _cache_key(p1, p2)

    # читаем кэш (мягко, если миграций ещё нет)
    try:
        rc = RouteCache.objects.filter(key=key).first()
    except (OperationalError, ProgrammingError) as e:
        if ROUTING_DEBUG:
            print(f"[routing] cache read failed: {repr(e)}")
        rc = None

    if rc and rc.updated_at > now() - timedelta(hours=ttl_hours):
        return rc

    # считаем через ORS
    try:
        km, minutes, raw, provider = _route_ors(p1, p2)
        if rc:
            rc.distance_km = km
            rc.duration_min = minutes
            rc.raw = raw
            rc.provider = provider
            try:
                rc.save(update_fields=["distance_km", "duration_min", "raw", "provider", "updated_at"])
            except (OperationalError, ProgrammingError) as e:
                if ROUTING_DEBUG:
                    print(f"[routing] cache update failed: {repr(e)}")
        else:
            try:
                rc = RouteCache.objects.create(
                    key=key,
                    origin_point=p1,
                    dest_point=p2,
                    provider=provider,
                    distance_km=km,
                    duration_min=minutes,
                    raw=raw,
                )
            except (OperationalError, ProgrammingError) as e:
                if ROUTING_DEBUG:
                    print(f"[routing] cache create failed: {repr(e)}")
                rc = None
        return rc
    except Exception as e:
        if ROUTING_DEBUG:
            print(f"[routing] _route_ors failed: {repr(e)}")
        return rc