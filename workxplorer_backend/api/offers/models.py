from django.conf import settings
from django.db import models
from django.db.models import UniqueConstraint
from django.apps import apps

from api.loads.models import Cargo, CargoStatus
from api.loads.choices import Currency, ModerationStatus


class Offer(models.Model):
    cargo = models.ForeignKey(Cargo, on_delete=models.CASCADE, related_name="offers")
    carrier = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="offers"
    )

    price_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    price_currency = models.CharField(
        max_length=3, choices=Currency.choices, default=Currency.UZS
    )
    message = models.TextField(blank=True)

    # согласия сторон
    accepted_by_customer = models.BooleanField(default=False)
    accepted_by_carrier = models.BooleanField(default=False)

    # техническое
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Один активный оффер от перевозчика на конкретный груз
            UniqueConstraint(fields=["cargo", "carrier"], name="uniq_offer_per_carrier_per_cargo"),
        ]
        indexes = [
            models.Index(fields=["cargo", "is_active"]),
            models.Index(fields=["carrier", "is_active"]),
        ]

    def __str__(self):
        return f"Offer#{self.pk} cargo={self.cargo_id} carrier={self.carrier_id}"

    # ---------------- Бизнес-логика ----------------

    def make_counter(self, *, price_value, price_currency=None, message=None):
        """
        Контр-предложение:
        - обновляет price_value/price_currency/message (если заданы),
        - сбрасывает акцепты обеих сторон,
        - оставляет оффер активным.
        """
        # цена
        if price_value is not None:
            self.price_value = price_value
        # валюта (опционально)
        if price_currency:
            self.price_currency = price_currency
        # сообщение/комментарий (опционально)
        if message is not None:
            self.message = message

        # сброс «принятости»
        self.accepted_by_customer = False
        self.accepted_by_carrier = False

        self.save(update_fields=[
            "price_value", "price_currency", "message",
            "accepted_by_customer", "accepted_by_carrier", "updated_at"
        ])

    @property
    def is_handshake(self) -> bool:
        return self.accepted_by_customer and self.accepted_by_carrier

    def _ensure_handshake_effects(self):
        """
        При взаимном согласии:
        - помечаем груз как MATCHED,
        - пробуем создать Shipment (если app 'shipments' установлен).
        """
        if not self.is_handshake:
            return

        # 1) Перевести груз в MATCHED
        if self.cargo.status != CargoStatus.MATCHED:
            self.cargo.status = CargoStatus.MATCHED
            self.cargo.save(update_fields=["status"])

        # 2) Создать Shipment (если приложение подключено)
        try:
            Shipment = apps.get_model("api.shipments", "Shipment")  # type: ignore
        except Exception:
            Shipment = None

        if Shipment:
            # Создаём только если ещё нет связанной перевозки
            exists = Shipment.objects.filter(offer=self).exists()
            if not exists:
                Shipment.objects.create(
                    load=self.cargo,               # в твоём проекте груз = Cargo
                    offer=self,
                    customer=self.cargo.customer,
                    carrier=self.carrier,
                    pickup_city=self.cargo.origin_city,
                    dropoff_city=self.cargo.destination_city,
                )

    def accept_by(self, user):
        """
        Акцепт со стороны клиента (владельца груза) или перевозчика.
        """
        if user.id == self.cargo.customer_id:
            if not self.accepted_by_customer:
                self.accepted_by_customer = True
                self.save(update_fields=["accepted_by_customer", "updated_at"])
        elif user.id == self.carrier_id:
            if not self.accepted_by_carrier:
                self.accepted_by_carrier = True
                self.save(update_fields=["accepted_by_carrier", "updated_at"])
        else:
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied("Нельзя принять чужой оффер")

        # если handshake — применяем эффекты
        if self.is_handshake:
            self._ensure_handshake_effects()

    def reject_by(self, user):
        """
        Отклонение со стороны любой из сторон — оффер деактивируется.
        """
        if user.id not in (self.cargo.customer_id, self.carrier_id):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied("Нельзя отклонить чужой оффер")

        if self.is_active:
            self.is_active = False
            self.save(update_fields=["is_active", "updated_at"])