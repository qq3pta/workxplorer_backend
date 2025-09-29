from django.contrib.gis.db import models as gis_models
from django.db import models


class RouteCache(models.Model):
    """
    Кэш маршрутов «точка А → точка Б», независимо от провайдера (Mapbox/ORS/OSRM).
    """

    key = models.CharField(max_length=128, unique=True)
    origin_point = gis_models.PointField(geography=True, srid=4326)
    dest_point = gis_models.PointField(geography=True, srid=4326)
    provider = models.CharField(max_length=32, default="osrm")
    distance_km = models.FloatField()
    duration_min = models.FloatField(null=True, blank=True)
    raw = models.JSONField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["provider", "key"], name="routing_pro_key_idx"),
        ]
        verbose_name = "Кэш маршрута"
        verbose_name_plural = "Кэш маршрутов"

    def __str__(self) -> str:
        return f"{self.provider}:{self.key}={self.distance_km:.1f}km"
