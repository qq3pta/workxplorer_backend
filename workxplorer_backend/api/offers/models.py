from django.db import models
from django.conf import settings
from django.db.models import Q
from ..loads.models import Cargo, CargoStatus
from ..loads.choices import Currency

class OfferStatus(models.TextChoices):
    PENDING = "PENDING", "Предложение"
    COUNTERED_BY_CUSTOMER = "COUNTERED_BY_CUSTOMER", "Ответ заказчика"
    ACCEPTED_BY_CUSTOMER = "ACCEPTED_BY_CUSTOMER", "Принято заказчиком (ждет подтверждения)"
    ACCEPTED = "ACCEPTED", "Сделка подтверждена"
    REJECTED = "REJECTED", "Отклонено"
    WITHDRAWN = "WITHDRAWN", "Отозвано"

class Offer(models.Model):
    cargo = models.ForeignKey(Cargo, on_delete=models.CASCADE, related_name="offers")
    carrier = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="offers_made")
    # Таргет-предложение (кнопка «Предложить») — опционально:
    targeted_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="offers_received")
    expires_at = models.DateTimeField(null=True, blank=True)

    amount_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    amount_currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.UZS)

    status = models.CharField(max_length=32, choices=OfferStatus.choices, default=OfferStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cargo", "carrier"],
                condition=Q(status__in=[OfferStatus.PENDING, OfferStatus.COUNTERED_BY_CUSTOMER, OfferStatus.ACCEPTED_BY_CUSTOMER]),
                name="uniq_active_offer_per_cargo_carrier",
            ),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"Offer#{self.pk} cargo={self.cargo_id} carrier={self.carrier_id} {self.amount_value} {self.amount_currency} [{self.status}]"

class OfferEventType(models.TextChoices):
    OFFERED = "OFFERED", "Предложение"
    COUNTER_FROM_CUSTOMER = "COUNTER_FROM_CUSTOMER", "Ответ заказчика"
    COUNTER_FROM_CARRIER = "COUNTER_FROM_CARRIER", "Ответ перевозчика"
    ACCEPT_BY_CUSTOMER = "ACCEPT_BY_CUSTOMER", "Принятие заказчиком"
    ACCEPT_BY_CARRIER = "ACCEPT_BY_CARRIER", "Подтверждение перевозчиком"
    REJECT_BY_CUSTOMER = "REJECT_BY_CUSTOMER", "Отклонено заказчиком"
    REJECT_BY_CARRIER = "REJECT_BY_CARRIER", "Отклонено перевозчиком"
    WITHDRAW_BY_CARRIER = "WITHDRAW_BY_CARRIER", "Отозвано перевозчиком"
    SYSTEM = "SYSTEM", "Система"

class OfferEvent(models.Model):
    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    type = models.CharField(max_length=32, choices=OfferEventType.choices)
    amount_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    amount_currency = models.CharField(max_length=3, choices=Currency.choices, null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"OfferEvent[{self.type}] offer={self.offer_id} by {self.actor_id}"