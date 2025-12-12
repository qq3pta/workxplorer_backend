from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Q, UniqueConstraint

from api.loads.choices import Currency
from api.loads.models import Cargo

# from api.loads.models import Cargo, CargoStatus
from api.orders.models import Order
from api.notifications.services import notify
from api.agreements.models import Agreement


class Offer(models.Model):
    class Initiator(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Заказчик"
        CARRIER = "CARRIER", "Перевозчик"
        LOGISTIC = "LOGISTIC", "Логист"

    cargo = models.ForeignKey(
        Cargo,
        on_delete=models.CASCADE,
        related_name="offers",
    )

    logistic = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="logistic_offers",
        limit_choices_to={"role": "LOGISTIC"},
    )

    intermediary = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="intermediary_offers",
        limit_choices_to={"role": "LOGISTIC"},
    )

    carrier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="offers",
        limit_choices_to={"role": "CARRIER"},
    )

    price_value = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    price_currency = models.CharField(
        max_length=3,
        choices=Currency.choices,
        default=Currency.UZS,
    )
    message = models.TextField(blank=True)

    accepted_by_customer = models.BooleanField(default=False)
    accepted_by_logistic = models.BooleanField(default=False)
    accepted_by_carrier = models.BooleanField(default=False)
    initiator = models.CharField(
        max_length=16,
        choices=Initiator.choices,
        default=Initiator.CARRIER,
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            UniqueConstraint(
                fields=["cargo", "carrier"],
                condition=Q(is_active=True),
                name="uniq_active_offer_per_carrier_per_cargo",
            ),
        ]
        indexes = [
            models.Index(fields=["cargo", "is_active"]),
            models.Index(fields=["carrier", "is_active"]),
            models.Index(fields=["initiator", "is_active"]),
        ]

    def __str__(self) -> str:
        return (
            f"Offer#{self.pk} cargo={self.cargo_id} carrier={self.carrier_id} by={self.initiator}"
        )

    @property
    def is_handshake(self):
        # CASE 1 — customer + carrier
        if self.accepted_by_customer and self.accepted_by_carrier:
            return True

        # CASE 2 — logistic(creator) + carrier
        if self.logistic and self.accepted_by_logistic and self.accepted_by_carrier:
            return True

        # CASE 3 — customer + logistic (NO_DRIVER)
        if (
            self.logistic is None
            and not self.accepted_by_carrier
            and self.accepted_by_customer
            and self.accepted_by_logistic
        ):
            return True

        # CASE 4 — logistic + logistic (NO_DRIVER)
        if (
            self.intermediary is not None
            and self.accepted_by_customer
            and self.accepted_by_logistic
            and not self.accepted_by_carrier
        ):
            return True

        return False

    def send_create_notifications(self):
        """Вызывается вручную из create() сериализатора."""
        customer = self.cargo.customer
        carrier = self.carrier

        notify(
            user=carrier,
            type="offer_sent",
            title="Предложение отправлено",
            message="Вы отправили предложение заказчику.",
            offer=self,
            cargo=self.cargo,
        )

        notify(
            user=customer,
            type="offer_received_from_carrier",
            title="Новое предложение",
            message="Вы получили предложение от перевозчика.",
            offer=self,
            cargo=self.cargo,
        )

    def send_invite_notifications(self):
        customer = self.cargo.customer
        carrier = self.carrier

        notify(
            user=customer,
            type="offer_sent",
            title="Инвайт отправлен",
            message="Вы отправили предложение перевозчику.",
            offer=self,
            cargo=self.cargo,
        )

        notify(
            user=carrier,
            type="offer_from_customer",
            title="Новое предложение от заказчика",
            message="Заказчик отправил вам предложение.",
            offer=self,
            cargo=self.cargo,
        )

    def send_counter_notifications(self, by_user):
        customer = self.cargo.customer
        carrier = self.carrier

        notify(
            user=by_user,
            type="offer_my_response_sent",
            title="Ответ отправлен",
            message="Вы предложили новые условия.",
            offer=self,
            cargo=self.cargo,
        )

        other = customer if by_user.id == carrier.id else carrier

        notify(
            user=other,
            type="offer_response_to_me",
            title="Получен ответ по предложению",
            message="По предложению поступил новый ответ.",
            offer=self,
            cargo=self.cargo,
        )

    def send_accept_notifications(self, accepted_by):
        customer = self.cargo.customer
        carrier = self.carrier

        if self.is_handshake:
            notify(
                user=customer,
                type="deal_success",
                title="Сделка подтверждена",
                message="Перевозчик подтвердил сделку.",
                offer=self,
                cargo=self.cargo,
            )
            notify(
                user=carrier,
                type="deal_success",
                title="Сделка подтверждена",
                message="Заказчик подтвердил сделку.",
                offer=self,
                cargo=self.cargo,
            )
            return

        other = customer if accepted_by.id == carrier.id else carrier

        notify(
            user=other,
            type="deal_confirm_required_by_other",
            title="Необходима подтвердить сделку",
            message="Другая сторона приняла предложение. Подтвердите сделку.",
            offer=self,
            cargo=self.cargo,
        )

    def send_reject_notifications(self, rejected_by):
        customer = self.cargo.customer
        carrier = self.carrier

        other = customer if rejected_by.id == carrier.id else carrier

        notify(
            user=other,
            type="deal_rejected_by_other",
            title="Предложение отклонено",
            message="Другая сторона отклонила предложение.",
            offer=self,
            cargo=self.cargo,
        )

    def reject_by(self, user):
        """
        Отклонение оффера одной из сторон.
        """
        role = getattr(user, "role", None)

        if not self.is_active:
            raise ValidationError("Оффер уже неактивен.")

        # --- CUSTOMER ---
        if role == "CUSTOMER" and user.id == self.cargo.customer_id:
            self.is_active = False
            self.accepted_by_customer = False

        # --- CARRIER ---
        elif role == "CARRIER" and user.id == self.carrier_id:
            self.is_active = False
            self.accepted_by_carrier = False

        # --- LOGISTIC ---
        elif role == "LOGISTIC" and (
            user.id == self.logistic_id or user.id == self.intermediary_id
        ):
            self.is_active = False
            self.accepted_by_logistic = False

        else:
            raise PermissionDenied("Вы не можете отклонить этот оффер.")

        self.save(
            update_fields=[
                "is_active",
                "accepted_by_customer",
                "accepted_by_carrier",
                "accepted_by_logistic",
                "updated_at",
            ]
        )

        self.send_reject_notifications(user)

    def make_counter(
        self,
        *,
        price_value: Decimal | None,
        price_currency: str | None = None,
        message: str | None = None,
        by_user=None,
    ) -> None:
        if price_value is not None:
            self.price_value = price_value
        if price_currency:
            self.price_currency = price_currency
        if message is not None:
            self.message = message

        if by_user is not None:
            if by_user.role == "LOGISTIC":
                self.initiator = self.Initiator.LOGISTIC
            elif by_user.id == self.cargo.customer_id:
                self.initiator = self.Initiator.CUSTOMER
            else:
                self.initiator = self.Initiator.CARRIER

        self.accepted_by_customer = False
        self.accepted_by_carrier = False
        self.accepted_by_logistic = False

        self.save(
            update_fields=[
                "price_value",
                "price_currency",
                "message",
                "initiator",
                "accepted_by_customer",
                "accepted_by_carrier",
                "accepted_by_logistic",
                "updated_at",
            ]
        )

        self.send_counter_notifications(by_user)

    def accept_by(self, user) -> None:
        if not self.is_active:
            raise ValidationError("Нельзя принять неактивный оффер.")

        # CUSTOMER принимает
        if user.role == "CUSTOMER" and user.id == self.cargo.customer_id:
            self.accepted_by_customer = True

        # CARRIER принимает
        elif user.role == "CARRIER" and user.id == self.carrier_id:
            self.accepted_by_carrier = True

        # LOGISTIC принимает
        elif user.role == "LOGISTIC":
            if user.id == self.cargo.customer_id:
                # Логист действует от имени заказчика
                self.accepted_by_customer = True
            else:
                self.accepted_by_logistic = True
                if self.intermediary is None:
                    self.intermediary = user
        else:
            raise PermissionDenied("Нельзя принять оффер: вы не участник сделки.")

        with transaction.atomic():
            self.save(
                update_fields=[
                    "accepted_by_customer",
                    "accepted_by_carrier",
                    "accepted_by_logistic",
                    "intermediary",
                    "updated_at",
                ]
            )

            # Отправка уведомлений
            self.send_accept_notifications(user)

            # Проверка handshake
            if self.is_handshake:
                # Создаём соглашение
                agreement = Agreement.get_or_create_from_offer(self)

                # Получаем объекты участников
                cargo = self.cargo
                customer = cargo.customer
                carrier = self.carrier
                logistic = self.intermediary or self.logistic

                # Проверка статусов и создание ордера
                if (
                    agreement.accepted_by_customer
                    and (agreement.accepted_by_carrier or carrier is None)
                    and (agreement.accepted_by_logistic or logistic is None)
                ):
                    # Защита от двойного создания
                    if cargo.status != "MATCHED" or cargo.chosen_offer_id != self.id:
                        cargo.status = "MATCHED"
                        cargo.assigned_carrier = carrier
                        cargo.chosen_offer = self
                        cargo.save(update_fields=["status", "assigned_carrier", "chosen_offer"])

                        Order.objects.create(
                            cargo=cargo,
                            customer=customer,
                            logistic=logistic,
                            carrier=carrier,
                            created_by=logistic or customer,
                            offer=self,
                            status=Order.OrderStatus.NO_DRIVER
                            if carrier is None
                            else Order.OrderStatus.PENDING,
                        )
                        # Деактивируем оффер
                        self.is_active = False
                        self.save(update_fields=["is_active"])

        print(f"ОТЛАДКА: Оффер {self.id} принят пользователем с ролью {user.role}, ID: {user.id}")
        print(f"ОТЛАДКА: Результат is_handshake: {self.is_handshake}")
        print(
            f"ОТЛАДКА: Флаги - заказчик: {self.accepted_by_customer}, логист: {self.accepted_by_logistic}, перевозчик: {self.accepted_by_carrier}"
        )
        print(
            f"ОТЛАДКА: Связанные ID - Логист_1: {self.logistic_id}, Логист_2 (Посредник): {self.intermediary_id}"
        )

        # if self.is_handshake:
        #    cargo_locked = (
        #        Cargo.objects.select_for_update()
        #        .only("id", "status", "assigned_carrier", "chosen_offer")
        #        .get(pk=self.cargo_id)
        #    )

        #    if cargo_locked.status == CargoStatus.MATCHED and getattr(
        #        cargo_locked, "chosen_offer_id", None
        #    ):
        #        return

        #    print("ОТЛАДКА: *** ВЫЗЫВАЕМ _FINALIZE_HANDSHAKE ***")
        #    self._finalize_handshake(cargo_locked=cargo_locked)

    # def _finalize_handshake(self, *, cargo_locked):
    #    customer = cargo_locked.customer
    #    intermediary = self.intermediary
    #    carrier = self.carrier

    #    creator = getattr(cargo_locked, "created_by", None)

    #    if creator is None:
    #        creator = customer

    # ---------------------------------------------
    # CASE 1 — CUSTOMER → CARRIER
    # ---------------------------------------------
    #    if creator.role == "CUSTOMER" and self.accepted_by_carrier:
    #        cargo_locked.status = CargoStatus.MATCHED
    #        cargo_locked.assigned_carrier_id = carrier.id
    #        cargo_locked.chosen_offer_id = self.id
    #        cargo_locked.save(update_fields=["status", "assigned_carrier_id", "chosen_offer_id"])

    #        Order.objects.create(
    #            cargo=cargo_locked,
    #            customer=customer,
    #            logistic=None,
    #            carrier=carrier,
    #            created_by=customer,
    #            offer=self,
    #            status=Order.OrderStatus.PENDING,
    #            driver_status=Order.DriverStatus.STOPPED,  # <-- ИСПРАВЛЕНО
    #        )
    #        return

    # ---------------------------------------------
    # CASE 2 — LOGISTIC → CARRIER
    # ---------------------------------------------
    # Создатель заявки — логист, принял перевозчик
    #    if creator.role == "LOGISTIC" and self.accepted_by_carrier:
    #        cargo_locked.status = CargoStatus.MATCHED
    #        cargo_locked.assigned_carrier_id = carrier.id
    #        cargo_locked.chosen_offer_id = self.id
    #        cargo_locked.save(update_fields=["status", "assigned_carrier_id", "chosen_offer_id"])

    #        Order.objects.create(
    #            cargo=cargo_locked,
    #            customer=customer,
    #            logistic=creator,
    #            carrier=carrier,
    #            created_by=creator,
    #            offer=self,
    #            status=Order.OrderStatus.PENDING,
    #            driver_status=Order.DriverStatus.STOPPED,
    #        )
    #        return

    # ---------------------------------------------
    # CASE 3 — CUSTOMER → LOGISTIC
    # ---------------------------------------------
    # Создатель — заказчик, принял логист
    #    if (
    #        creator.role == "CUSTOMER"
    #        and self.accepted_by_customer
    #        and self.accepted_by_logistic
    #        and not self.accepted_by_carrier
    #    ):
    #        cargo_locked.status = CargoStatus.MATCHED
    #        cargo_locked.chosen_offer_id = self.id
    #        cargo_locked.save(update_fields=["status", "chosen_offer_id"])

    #        Order.objects.create(
    #            cargo=cargo_locked,
    #            customer=customer,
    #            logistic=intermediary,  # <-- ИСПРАВЛЕНО: Теперь используется intermediary
    #            carrier=None,
    #            created_by=intermediary,  # <-- ИСПРАВЛЕНО: Теперь используется intermediary
    #            offer=self,
    #            status=Order.OrderStatus.NO_DRIVER,
    #            driver_status=Order.DriverStatus.STOPPED,  # <-- ИСПРАВЛЕНО
    #        )
    #        return

    # ---------------------------------------------
    # CASE 4 — LOGISTIC → LOGISTIC
    # ---------------------------------------------
    # Создатель — логист 1, принял логист 2
    #    if (
    #        creator.role == "LOGISTIC"
    #        and intermediary
    #        and self.accepted_by_customer
    #        and self.accepted_by_logistic
    #        and not self.accepted_by_carrier
    #    ):
    #        print("ОТЛАДКА: !!! ПОПАЛИ В КЕЙС 4 - СОЗДАНИЕ ЗАКАЗА !!!")
    #        print(
    #            f"ОТЛАДКА: Роль Создателя: {creator.role}, ID Посредника: {intermediary.id}, ID Логиста_1: {self.logistic_id}"
    #        )

    #        cargo_locked.status = CargoStatus.MATCHED
    #        cargo_locked.chosen_offer_id = self.id
    #        cargo_locked.save(update_fields=["status", "chosen_offer_id"])

    #        Order.objects.create(
    #            cargo=cargo_locked,
    #            customer=customer,
    #            logistic=intermediary,
    #            carrier=None,
    #            created_by=intermediary,
    #            offer=self,
    #            status=Order.OrderStatus.NO_DRIVER,
    #            driver_status=Order.DriverStatus.STOPPED,
    #        )
    #        print("ОТЛАДКА: ЗАКАЗ УСПЕШНО СОЗДАН (Кейс 4)")
    #        return

    #    # Если ни один из кейсов не сработал — НИЧЕГО не создаём
    #    print("ОТЛАДКА: Завершение сделки НЕ УДАЛОСЬ - Ни один кейс не сработал.")
    #    return
