from django.db import models
from django.conf import settings

class CargoStatus(models.TextChoices):
    POSTED = "POSTED", "Опубликована"
    MATCHED = "MATCHED", "В работе"
    DELIVERED = "DELIVERED", "Доставлено"
    COMPLETED = "COMPLETED", "Завершено"

class Cargo(models.Model):
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cargos"
    )
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    pickup_city = models.CharField(max_length=100)
    delivery_city = models.CharField(max_length=100)
    weight=kg = models.DecimalField(max_digits=10, decimal_places=2)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    pickup_date = models.DateField(null=True, blank=True)
    status = models.CharField(choices=CargoStatus.choices, default=CargoStatus.POSTED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.pickup_city} > {self.delivery_city})"
