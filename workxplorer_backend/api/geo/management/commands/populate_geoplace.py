import time
from django.core.management.base import BaseCommand
from django.contrib.gis.geos import Point

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

# Популярные города каждой страны
POPULAR_CITIES = {
    "KZ": ["Нур-Султан", "Алматы", "Шымкент", "Караганда", "Актобе"],
    "UZ": ["Ташкент", "Самарканд", "Бухара", "Наманган", "Андижан"],
    "KG": ["Бишкек", "Ош", "Жалал-Абад", "Каракол"],
    "TJ": ["Душанбе", "Худжанд", "Бохтар", "Куляб"],
    "TM": ["Ашхабад", "Туркменабад", "Мары"],
    "CN": ["Пекин", "Шанхай", "Гуанчжоу", "Шэньчжэнь", "Чэнду"],
    "MN": ["Улан-Батор", "Дархан", "Эрдэнэт"],
    "AF": ["Кабул", "Кандагар", "Герат", "Мазари-Шариф"],
    "PK": ["Исламабад", "Карачи", "Лахор", "Фейсалабад"],
    "IN": ["Нью-Дели", "Мумбаи", "Бангалор", "Ченнай", "Хайдарабад"],
    "AZ": ["Баку", "Гянджа", "Сумгайыт"],
    "AM": ["Ереван", "Гюмри", "Ванадзор"],
    "GE": ["Тбилиси", "Батуми", "Кутаиси"],
    "TR": ["Анкара", "Стамбул", "Измир", "Бурса"],
    "IR": ["Тегеран", "Мешхед", "Исфахан", "Шираз"],
    "RU": ["Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань"],
    "BY": ["Минск", "Гомель", "Могилёв", "Витебск"],
    "UA": ["Киев", "Харьков", "Одесса", "Днепр", "Львов"],
    "PL": ["Варшава", "Краков", "Гданьск", "Вроцлав", "Познань"],
    "HU": ["Будапешт", "Дебрецен", "Сегед", "Мишкольц"],
    "RO": ["Бухарест", "Клуж-Напока", "Тимишоара", "Яссы"],
    "BG": ["София", "Пловдив", "Варна", "Бургас"],
    "RS": ["Белград", "Нови-Сад", "Ниш"],
    "GR": ["Афины", "Салоники", "Патры"],
}


class Command(BaseCommand):
    help = "Добавляет страны и популярные города в GeoPlace"

    def handle(self, *args, **options):
        for country in ISO_COUNTRIES:
            code = country["code"]
            name = country["name"]

            # Добавляем страну без координат
            GeoPlace.objects.update_or_create(
                country_code=code,
                name=name,
                defaults={
                    "country": name,
                    "point": None,  # оставляем пустым
                    "provider": "manual",
                    "raw": None,
                },
            )
            self.stdout.write(f"Страна добавлена: {name}")

            # Добавляем популярные города без геокодирования
            for city_name in POPULAR_CITIES.get(code, []):
                GeoPlace.objects.update_or_create(
                    country_code=code,
                    name=city_name,
                    defaults={
                        "country": name,
                        "point": None,
                        "provider": "manual",
                        "raw": None,
                    },
                )
                self.stdout.write(f"Город добавлен: {city_name} ({code})")
