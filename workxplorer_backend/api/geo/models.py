from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.indexes import GistIndex
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import UniqueConstraint
from django.db.models.functions import Lower


class GeoPlace(models.Model):
    name = models.CharField(max_length=128)
    country = models.CharField(max_length=128)
    country_code = models.CharField(
        max_length=2,
        validators=[RegexValidator(r'^[A-Z]{2}$', message='ISO-2 код страны, например UZ, KZ')]
    )
    point = gis_models.PointField(geography=True, srid=4326)
    provider = models.CharField(max_length=32, default="nominatim")
    raw = models.JSONField(null=True, blank=True)
    last_verified_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                Lower('name'),
                'country_code',
                name='uq_geoplace_lower_name_country_code',
            )
        ]
        indexes = [
            GistIndex(fields=["point"], name="geoplace_point_gix"),
            models.Index(fields=["country_code", "name"], name="geoplace_cc_name_idx"),
            models.Index(Lower('name'), name='geoplace_lower_name_idx'),
        ]
        ordering = ["country_code", "name"]

    def __str__(self):
        return f"{self.name}, {self.country_code}"
    def save(self, *args, **kwargs):
        if self.name:
            self.name = self.name.strip()
        if self.country:
            self.country = self.country.strip()
        if self.country_code:
            self.country_code = self.country_code.strip().upper()[:2]
        super().save(*args, **kwargs)