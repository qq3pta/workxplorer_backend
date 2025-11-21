from django.core.management.base import BaseCommand
from api.loads.models import Cargo
from django.contrib.gis.geos import Point  # noqa: F401
from api.geo.models import GeoPlace  # noqa: F401
from api.loads.serializers import CargoPublishSerializer


class Command(BaseCommand):
    help = "Заполняет координаты грузов в GeoPlace"

    def handle(self, *args, **options):
        serializer = CargoPublishSerializer()

        # --- Заполнение origin_point ---
        missing_origin = Cargo.objects.filter(origin_point__isnull=True)
        for c in missing_origin:
            try:
                c.origin_point = serializer._geocode_origin(
                    {"origin_country": c.origin_country, "origin_city": c.origin_city}
                )
                c.save()
                self.stdout.write(
                    f"Origin point обновлён: {c.origin_city}, {c.origin_country} для груза {c.id}"
                )
            except Exception as e:
                self.stdout.write(
                    f"Не удалось геокодировать origin: {c.origin_city}, {c.origin_country}. Ошибка: {e}"
                )

        # --- Заполнение dest_point ---
        missing_dest = Cargo.objects.filter(dest_point__isnull=True)
        for c in missing_dest:
            try:
                c.dest_point = serializer._geocode_dest(
                    {
                        "destination_country": c.destination_country,
                        "destination_city": c.destination_city,
                    }
                )
                c.save()
                self.stdout.write(
                    f"Destination point обновлён: {c.destination_city}, {c.destination_country} для груза {c.id}"
                )
            except Exception as e:
                self.stdout.write(
                    f"Не удалось геокодировать dest: {c.destination_city}, {c.destination_country}. Ошибка: {e}"
                )

        # --- Пример ручного добавления города в GeoPlace ---
        # GeoPlace.objects.create(
        #     name="Moscow",
        #     country="Russia",
        #     country_code="RU",
        #     point=Point(37.6173, 55.7558)  # lon, lat
        # )
