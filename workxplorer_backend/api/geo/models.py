from django.contrib.gis.db import models as gis_models
from django.db import models
from django.contrib.postgres.indexes import GistIndex

class GeoPlace(models.Model):
    name = models.CharField(max_length=128)
    country = models.CharField(max_length=128)
    country_code = models.CharField(max_length=2)
    point = gis_models.PointField(geography=True, srid=4326)
    provider = models.CharField(max_length=32, default="nominatim")
    raw = models.JSONField(null=True, blank=True)
    last_verified_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("name", "country_code")]
        indexes = [
            GistIndex(fields=["point"], name="geoplace_point_gix"),
            models.Index(fields=["country_code", "name"]),
        ]

    def __str__(self):
        return f"{self.name}, {self.country_code}"