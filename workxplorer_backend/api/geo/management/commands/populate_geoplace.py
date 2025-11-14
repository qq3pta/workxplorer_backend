import time
from django.core.management.base import BaseCommand
from django.contrib.gis.geos import Point
from django.conf import settings
import requests

from api.geo.models import GeoPlace

# Список стран ISO-2 и названия
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

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
ALLOWED_PLACE_TYPES = {"city", "town", "village", "hamlet", "locality"}


def geocode_city(country_code, city_name, lang="ru"):
    """Возвращает Point для города через Nominatim"""
    headers = {
        "User-Agent": getattr(settings, "GEO_NOMINATIM_USER_AGENT", "workxplorer/geo-populate"),
        "Accept-Language": lang,
    }
    params = {
        "q": city_name,
        "format": "json",
        "addressdetails": 1,
        "namedetails": 1,
        "limit": 5,
        "countrycodes": country_code.lower(),
    }

    try:
        time.sleep(1)  # чтобы не превышать rate limit
        r = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        for item in data:
            if item.get("class") != "place":
                continue
            if item.get("type") not in ALLOWED_PLACE_TYPES:
                continue
            lat = float(item["lat"])
            lon = float(item["lon"])
            return Point(lon, lat), item
    except Exception as e:
        print(f"Ошибка при геокодировании {city_name}: {e}")
    return None, None


class Command(BaseCommand):
    help = "Заполняет таблицу GeoPlace странами и крупными городами"

    def handle(self, *args, **options):
        capitals = {
            "KZ": "Нур-Султан",
            "UZ": "Ташкент",
            "KG": "Бишкек",
            "TJ": "Душанбе",
            "TM": "Ашхабад",
            "CN": "Пекин",
            "MN": "Улан-Батор",
            "AF": "Кабул",
            "PK": "Исламабад",
            "IN": "Нью-Дели",
            "AZ": "Баку",
            "AM": "Ереван",
            "GE": "Тбилиси",
            "TR": "Анкара",
            "IR": "Тегеран",
            "RU": "Москва",
            "BY": "Минск",
            "UA": "Киев",
            "PL": "Варшава",
            "HU": "Будапешт",
            "RO": "Бухарест",
            "BG": "София",
            "RS": "Белград",
            "GR": "Афины",
        }

        for country in ISO_COUNTRIES:
            code = country["code"]
            name = country["name"]

            # 1) Добавляем страну без координат
            GeoPlace.objects.update_or_create(
                country_code=code,
                name=name,
                defaults={
                    "country": name,
                    "point": None,  # разрешаем null
                    "provider": "manual",
                },
            )
            self.stdout.write(f"Добавлена страна: {name}")

            # 2) Добавляем столицу с координатами через Nominatim
            city_name = capitals.get(code)
            if city_name:
                point, raw = geocode_city(code, city_name)
                GeoPlace.objects.update_or_create(
                    country_code=code,
                    name=city_name,
                    defaults={
                        "country": name,
                        "point": point,
                        "provider": "nominatim",
                        "raw": raw,
                    },
                )
                self.stdout.write(f"Добавлен город: {city_name} ({code})")
