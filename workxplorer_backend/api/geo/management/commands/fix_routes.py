from django.core.management.base import BaseCommand
from django.contrib.gis.geos import Point
from django.db.models import Q
from unidecode import unidecode

from api.loads.models import Cargo
from api.geo.models import GeoPlace


class Command(BaseCommand):
    help = "Fix missing origin_point / dest_point / route_km_cached for all cargos"

    def handle(self, *args, **options):
        fixed_points = 0
        fixed_routes = 0

        cargos = Cargo.objects.all()

        for cargo in cargos:
            origin_city = cargo.origin_city.strip()
            dest_city = cargo.destination_city.strip()

            # -----------------------------
            # ORIGIN FIX
            # -----------------------------
            if not cargo.origin_point:
                cargo.origin_point = self.find_point(cargo.origin_country, origin_city)
                if cargo.origin_point:
                    fixed_points += 1
                    self.stdout.write(self.style.SUCCESS(f"[OK] Origin fixed → {origin_city}"))

            # -----------------------------
            # DEST FIX
            # -----------------------------
            if not cargo.dest_point:
                cargo.dest_point = self.find_point(cargo.destination_country, dest_city)
                if cargo.dest_point:
                    fixed_points += 1
                    self.stdout.write(self.style.SUCCESS(f"[OK] Destination fixed → {dest_city}"))

            # Обновить запись если есть изменения в точках
            if cargo.origin_point or cargo.dest_point:
                cargo.save(update_fields=["origin_point", "dest_point"])

            # -----------------------------
            # ROUTE CACHE FIX
            # -----------------------------
            if cargo.origin_point and cargo.dest_point:
                if cargo.route_km_cached is None:
                    route = cargo.update_route_cache(save=True)
                    if route:
                        fixed_routes += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"[OK] Route cached for {origin_city} → {dest_city}: {route:.1f} km"
                            )
                        )

        self.stdout.write(self.style.NOTICE("------ FINISHED ------"))
        self.stdout.write(self.style.SUCCESS(f"Points fixed: {fixed_points}"))
        self.stdout.write(self.style.SUCCESS(f"Routes recalculated: {fixed_routes}"))

    # ------------------------------------------------------------
    # Найти геоточку по city (кириллица / латиница / транслит)
    # ------------------------------------------------------------
    def find_point(self, country: str, city: str) -> Point | None:
        if not city:
            return None

        city_norm = city.lower()
        city_lat = unidecode(city_norm).lower()

        # Ищем в GeoPlace по name и name_latin
        gp = (
            GeoPlace.objects.filter(country__iexact=country)
            .filter(
                Q(name__iexact=city_norm)
                | Q(name_latin__iexact=city_norm)
                | Q(name_latin__iexact=city_lat)
                | Q(name__icontains=city_norm)
                | Q(name_latin__icontains=city_lat)
            )
            .first()
        )

        if gp and gp.point:
            return gp.point

        return None
