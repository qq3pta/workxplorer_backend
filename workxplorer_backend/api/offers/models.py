from __future__ import annotations

from decimal import Decimal
from datetime import date, datetime


import logging

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Q, UniqueConstraint

from api.loads.choices import Currency
from api.loads.models import Cargo
from api.notifications.services import notify

logger = logging.getLogger(__name__)


def json_safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(v) for v in value]
    return value


class Offer(models.Model):
    class Initiator(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Заказчик"
        CARRIER = "CARRIER", "Перевозчик"
        LOGISTIC = "LOGISTIC", "Логист"

    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Наличные"
        CASHLESS = "cashless", "Безналичный расчёт"
        BOTH = "both", "Наличные + перечисление"

    class DealType(models.TextChoices):
        CUSTOMER_CARRIER = "customer_carrier"
        LOGISTIC_CARRIER = "logistic_carrier"
        CUSTOMER_LOGISTIC = "customer_logistic"
        LOGISTIC_LOGISTIC = "logistic_logistic"

    deal_type = models.CharField(
        max_length=32,
        choices=DealType.choices,
    )

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

    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
    )

    driver_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    driver_currency = models.CharField(max_length=10, null=True, blank=True)

    driver_payment_method = models.CharField(max_length=50, null=True, blank=True)

    message = models.TextField(blank=True)

    accepted_by_customer = models.BooleanField(default=False)
    accepted_by_logistic = models.BooleanField(default=False)
    accepted_by_carrier = models.BooleanField(default=False)
    initiator = models.CharField(
        max_length=16,
        choices=Initiator.choices,
        default=Initiator.CARRIER,
    )

    response_status = models.CharField(
        max_length=32,
        blank=True,
        null=True,
        default="",
    )
    is_counter = models.BooleanField(default=False)

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
    def is_handshake(self) -> bool:
        kind = self.deal_type

        if kind in {
            self.DealType.CUSTOMER_CARRIER,
            self.DealType.LOGISTIC_CARRIER,
        }:
            return self.accepted_by_customer and self.accepted_by_carrier

        if kind == self.DealType.CUSTOMER_LOGISTIC:
            return self.accepted_by_customer and self.accepted_by_logistic

        if kind == self.DealType.LOGISTIC_LOGISTIC:
            return self.accepted_by_logistic

        return False

    def _log_status_change(self, *, user, action, old_state):
        OfferStatusLog.objects.create(
            offer=self,
            user=user,
            action=action,
            old_state=json_safe(old_state),
            new_state=json_safe(
                {
                    "price_value": self.price_value,
                    "price_currency": self.price_currency,
                    "payment_method": self.payment_method,
                    "message": self.message,
                    "initiator": self.initiator,
                    "is_active": self.is_active,
                    "is_counter": self.is_counter,
                    "response_status": self.response_status,
                    "accepted_by_customer": self.accepted_by_customer,
                    "accepted_by_carrier": self.accepted_by_carrier,
                    "accepted_by_logistic": self.accepted_by_logistic,
                }
            ),
        )

    # ---------------- Notifications ----------------
    def send_create_notifications(self):
        customer = self.cargo.customer
        carrier = self.carrier
        logistic_user = self.intermediary or self.logistic

        print("\n[MODEL send_create_notifications]")
        print("offer.id =", self.id, "deal_type =", self.deal_type, "initiator =", self.initiator)
        print("customer.id =", getattr(customer, "id", None))
        print("carrier.id =", getattr(carrier, "id", None))
        print("logistic.id =", getattr(logistic_user, "id", None))

        # 1) Оффер от перевозчика заказчику
        if self.initiator == self.Initiator.CARRIER:
            if carrier:
                notify(
                    user=carrier,
                    type="offer_sent",
                    title="Предложение отправлено",
                    message="Вы отправили предложение заказчику.",
                    offer=self,
                    cargo=self.cargo,
                )
            else:
                print("[MODEL send_create_notifications] SKIP notify carrier (carrier is None)")

            if customer:
                notify(
                    user=customer,
                    type="offer_received_from_carrier",
                    title="Новое предложение",
                    message="Вы получили предложение от перевозчика.",
                    offer=self,
                    cargo=self.cargo,
                )
            else:
                print("[MODEL send_create_notifications] SKIP notify customer (customer is None)")

            return

        # 2) Оффер от логиста заказчику
        if self.initiator == self.Initiator.LOGISTIC:
            if logistic_user:
                notify(
                    user=logistic_user,
                    type="offer_sent",
                    title="Предложение отправлено",
                    message="Вы отправили предложение заказчику.",
                    offer=self,
                    cargo=self.cargo,
                )
            else:
                print(
                    "[MODEL send_create_notifications] SKIP notify logistic_user (logistic_user is None)"
                )

            if customer:
                notify(
                    user=customer,
                    type="offer_received_from_logistic",
                    title="Новое предложение",
                    message="Вы получили предложение от логиста.",
                    offer=self,
                    cargo=self.cargo,
                )
            else:
                print("[MODEL send_create_notifications] SKIP notify customer (customer is None)")

            return

        print("[MODEL send_create_notifications] Unknown initiator -> no notifications")

    def send_invite_notifications(self):
        customer = self.cargo.customer
        recipient = self.carrier or self.logistic or self.intermediary

        if customer:
            notify(
                user=customer,
                type="offer_sent",
                title="Инвайт отправлен",
                message="Вы отправили предложение.",
                offer=self,
                cargo=self.cargo,
            )

        if recipient:
            notify(
                user=recipient,
                type="offer_from_customer",
                title="Новое предложение",
                message="Вам отправлено новое предложение.",
                offer=self,
                cargo=self.cargo,
            )

    def send_counter_notifications(self, by_user):
        customer = self.cargo.customer
        carrier = self.carrier
        logistic_user = self.intermediary or self.logistic

        # уведомление инициатору
        notify(
            user=by_user,
            type="offer_my_response_sent",
            title="Ответ отправлен",
            message="Вы предложили новые условия.",
            offer=self,
            cargo=self.cargo,
        )

        other = None

        # --- customer ↔ carrier ---
        if carrier:
            if by_user.id == carrier.id:
                other = customer
            else:
                other = carrier

        # --- customer ↔ logistic ---
        elif logistic_user:
            if by_user.id == customer.id:
                other = logistic_user
            else:
                other = customer

        if not other:
            return

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
        logistic_user = self.intermediary or self.logistic

        print("\n[MODEL send_accept_notifications]")
        print("offer.id =", self.id, "deal_type =", self.deal_type)
        print(
            "accepted_by.id =",
            getattr(accepted_by, "id", None),
            "role =",
            getattr(accepted_by, "role", None),
        )
        print("customer.id =", getattr(customer, "id", None))
        print("carrier.id =", getattr(carrier, "id", None))
        print("logistic.id =", getattr(logistic_user, "id", None))
        print("is_handshake =", self.is_handshake)

        # === SUCCESS ===
        if self.is_handshake:
            # customer <-> carrier
            if self.deal_type in {self.DealType.CUSTOMER_CARRIER, self.DealType.LOGISTIC_CARRIER}:
                if customer:
                    notify(
                        user=customer,
                        type="deal_success",
                        title="Сделка подтверждена",
                        message="Перевозчик подтвердил сделку.",
                        offer=self,
                        cargo=self.cargo,
                    )
                if carrier:
                    notify(
                        user=carrier,
                        type="deal_success",
                        title="Сделка подтверждена",
                        message="Заказчик подтвердил сделку.",
                        offer=self,
                        cargo=self.cargo,
                    )
                return

            # customer <-> logistic
            if self.deal_type == self.DealType.CUSTOMER_LOGISTIC:
                if customer:
                    notify(
                        user=customer,
                        type="deal_success",
                        title="Сделка подтверждена",
                        message="Логист подтвердил сделку.",
                        offer=self,
                        cargo=self.cargo,
                    )
                if logistic_user:
                    notify(
                        user=logistic_user,
                        type="deal_success",
                        title="Сделка подтверждена",
                        message="Заказчик подтвердил сделку.",
                        offer=self,
                        cargo=self.cargo,
                    )
                return

            # logistic only
            if self.deal_type == self.DealType.LOGISTIC_LOGISTIC:
                if logistic_user:
                    notify(
                        user=logistic_user,
                        type="deal_success",
                        title="Сделка подтверждена",
                        message="Соглашение подтверждено.",
                        offer=self,
                        cargo=self.cargo,
                    )
                return

        # === CONFIRM REQUIRED ===
        # определяем "другую сторону"
        other = None

        if self.deal_type in {self.DealType.CUSTOMER_CARRIER, self.DealType.LOGISTIC_CARRIER}:
            # сравнение делаем безопасно, без carrier.id если carrier=None
            if carrier and accepted_by and accepted_by.id == carrier.id:
                other = customer
            else:
                other = carrier

        elif self.deal_type == self.DealType.CUSTOMER_LOGISTIC:
            if accepted_by and accepted_by.id == getattr(customer, "id", None):
                other = logistic_user
            else:
                other = customer

        elif self.deal_type == self.DealType.LOGISTIC_LOGISTIC:
            other = logistic_user

        print(
            "[MODEL send_accept_notifications] other.id =",
            getattr(other, "id", None),
            getattr(other, "role", None),
        )

        if not other:
            print("[MODEL send_accept_notifications] SKIP notify other (other is None)")
            return

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
        logistic_user = self.intermediary or self.logistic

        other = None

        # customer ↔ carrier
        if self.deal_type in {
            self.DealType.CUSTOMER_CARRIER,
            self.DealType.LOGISTIC_CARRIER,
        }:
            if carrier and rejected_by.id == carrier.id:
                other = customer
            else:
                other = carrier

        # customer ↔ logistic
        elif self.deal_type == self.DealType.CUSTOMER_LOGISTIC:
            if rejected_by.id == getattr(customer, "id", None):
                other = logistic_user
            else:
                other = customer

        # logistic ↔ logistic
        elif self.deal_type == self.DealType.LOGISTIC_LOGISTIC:
            other = logistic_user

        if not other:
            return  # ✔ никого уведомлять не нужно

        notify(
            user=other,
            type="deal_rejected_by_other",
            title="Предложение отклонено",
            message="Другая сторона отклонила предложение.",
            offer=self,
            cargo=self.cargo,
        )

    # ---------------- Reject ----------------
    def reject_by(self, user):
        if not self.is_active:
            return

        old_state = {
            "accepted_by_customer": self.accepted_by_customer,
            "accepted_by_carrier": self.accepted_by_carrier,
            "accepted_by_logistic": self.accepted_by_logistic,
            "is_counter": self.is_counter,
            "response_status": self.response_status,
        }

        # --- бизнес-логика ---
        if user.id in (self.cargo.customer_id, self.cargo.created_by_id):
            self.accepted_by_customer = False
            self.response_status = "rejected_by_customer"

        elif user.role == "CARRIER" and user.id == self.carrier_id:
            self.accepted_by_carrier = False
            self.response_status = "rejected_by_carrier"

        elif user.role == "LOGISTIC" and user.id in (self.logistic_id, self.intermediary_id):
            self.accepted_by_logistic = False
            self.response_status = "rejected_by_logistic"

        else:
            raise PermissionDenied("Вы не можете отклонить этот оффер.")

        self.save(
            update_fields=[
                "accepted_by_customer",
                "accepted_by_carrier",
                "accepted_by_logistic",
                "response_status",
                "updated_at",
            ]
        )

        self._log_status_change(
            user=user,
            action="reject",
            old_state=old_state,
        )

        self.send_reject_notifications(user)

    # ---------------- Make Counter ----------------
    def make_counter(
        self,
        *,
        price_value: Decimal | None,
        price_currency: str | None = None,
        payment_method: str | None = None,
        message: str | None = None,
        by_user=None,
    ) -> None:
        # ✅ OLD STATE
        old_state = {
            "price_value": self.price_value,
            "price_currency": self.price_currency,
            "payment_method": self.payment_method,
            "message": self.message,
            "initiator": self.initiator,
            "is_counter": self.is_counter,
            "response_status": self.response_status,
        }

        # --- бизнес-логика ---
        if price_value is not None:
            self.price_value = price_value
        if price_currency:
            self.price_currency = price_currency
        if payment_method:
            self.payment_method = payment_method
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
        self.is_counter = True

        if by_user is not None:
            if self.initiator == self.Initiator.CUSTOMER:
                self.response_status = "counter_from_customer"
            elif self.initiator == self.Initiator.LOGISTIC and by_user.id == self.cargo.customer_id:
                self.response_status = "counter_from_customer"
            else:
                self.response_status = "counter"

        self.save(
            update_fields=[
                "price_value",
                "price_currency",
                "payment_method",
                "message",
                "initiator",
                "accepted_by_customer",
                "accepted_by_carrier",
                "accepted_by_logistic",
                "is_counter",
                "response_status",
                "updated_at",
            ]
        )

        # ✅ LOG COUNTER
        self._log_status_change(
            user=by_user,
            action="counter",
            old_state=old_state,
        )

        if by_user is not None:
            _ = self.get_response_status_for(by_user)

        self.send_counter_notifications(by_user)

    @staticmethod
    def resolve_deal_type(*, initiator_user, carrier=None, logistic=None) -> str:
        role = getattr(initiator_user, "role", None)

        # Перевозчик → всегда заказчику
        if role == "CARRIER":
            return Offer.DealType.CUSTOMER_CARRIER

        # Заказчик
        if role == "CUSTOMER":
            if logistic and not carrier:
                return Offer.DealType.CUSTOMER_LOGISTIC
            return Offer.DealType.CUSTOMER_CARRIER

        # ЛОГИСТ
        if role == "LOGISTIC":
            # 🔑 КЕЙС 3: логист → заказчик (без перевозчика)
            if not carrier:
                return Offer.DealType.CUSTOMER_LOGISTIC

            # логист + перевозчик
            return Offer.DealType.LOGISTIC_CARRIER

        raise ValidationError("Невозможно определить тип сделки")

    # ---------------- Accept Dispatcher ----------------
    def accept_by(self, user) -> None:
        print("\n[MODEL accept_by]")

        if not self.deal_type:
            logger.warning("Offer %s has empty deal_type. Resolving automatically.", self.id)
            self.deal_type = Offer.resolve_deal_type(
                initiator_user=self.cargo.customer,
                carrier=self.carrier,
                logistic=self.logistic or self.intermediary,
            )
            self.save(update_fields=["deal_type"])

        print("user.id =", user.id, "role =", user.role)
        print("deal_type =", self.deal_type)
        print(
            "flags BEFORE:",
            "customer =",
            self.accepted_by_customer,
            "logistic =",
            self.accepted_by_logistic,
            "carrier =",
            self.accepted_by_carrier,
        )

        if not self.is_active:
            if (
                (
                    user.id in (self.cargo.customer_id, self.cargo.created_by_id)
                    and self.accepted_by_customer
                )
                or (
                    user.role == "CARRIER"
                    and user.id == self.carrier_id
                    and self.accepted_by_carrier
                )
                or (
                    user.role == "LOGISTIC"
                    and user.id in (self.logistic_id, self.intermediary_id)
                    and self.accepted_by_logistic
                )
            ):
                return

            raise ValidationError("Оффер уже закрыт.")

        handlers = {
            self.DealType.CUSTOMER_CARRIER: self._accept_case_customer_carrier,
            self.DealType.LOGISTIC_CARRIER: self._accept_case_logistic_carrier,
            self.DealType.CUSTOMER_LOGISTIC: self._accept_case_customer_logistic,
            self.DealType.LOGISTIC_LOGISTIC: self._accept_case_logistic_logistic,
        }

        handler = handlers.get(self.deal_type)
        if not handler:
            raise ValidationError("Неизвестный тип сделки")

        handler(user)

    # ---------------- CASES ----------------
    def _accept_case_customer_carrier(self, user):
        cargo = self.cargo
        old_state = {
            "accepted_by_customer": self.accepted_by_customer,
            "accepted_by_carrier": self.accepted_by_carrier,
            "accepted_by_logistic": self.accepted_by_logistic,
        }

        # ✅ 2. БИЗНЕС-ЛОГИКА
        if user.id in (cargo.customer_id, cargo.created_by_id):
            self.accepted_by_customer = True
        elif user.role == "CARRIER" and user.id == self.carrier_id:
            self.accepted_by_carrier = True
        else:
            raise PermissionDenied("Недопустимый участник для данного кейса")

        # ✅ 3. ATOMIC + SAVE + LOG + NOTIFY
        with transaction.atomic():
            self.save(update_fields=["accepted_by_customer", "accepted_by_carrier", "updated_at"])

            self._log_status_change(
                user=user,
                action="accept",
                old_state=old_state,
            )

            self.send_accept_notifications(user)

            # ✅ 4. СОЗДАНИЕ AGREEMENT ТОЛЬКО ПРИ HANDSHAKE
            if self.accepted_by_customer and self.accepted_by_carrier:
                # 🔥 ФИКС ФИНАЛЬНОГО СТАТУСА
                self.response_status = "accepted"
                self.is_active = True

                self.save(update_fields=["response_status", "is_active", "updated_at"])

                from api.agreements.models import Agreement

                Agreement.get_or_create_from_offer(self)

    def _accept_case_logistic_carrier(self, user):
        # ✅ 1. OLD STATE ДО ИЗМЕНЕНИЙ
        old_state = {
            "accepted_by_customer": self.accepted_by_customer,
            "accepted_by_carrier": self.accepted_by_carrier,
            "accepted_by_logistic": self.accepted_by_logistic,
        }

        # ✅ 2. БИЗНЕС-ЛОГИКА
        if user.role == "LOGISTIC":
            if user.id in (self.logistic_id, self.intermediary_id):
                self.accepted_by_logistic = True
            elif self.intermediary is None:
                self.accepted_by_logistic = True
                self.intermediary = user
            else:
                raise PermissionDenied("Логист не является участником этого оффера")

        elif user.role == "CARRIER" and user.id == self.carrier_id:
            self.accepted_by_carrier = True
        else:
            raise PermissionDenied("Недопустимый участник для данного кейса")

        # ✅ 3. SAVE + LOG + NOTIFY + AGREEMENT
        with transaction.atomic():
            self.save(
                update_fields=[
                    "accepted_by_logistic",
                    "accepted_by_carrier",
                    "intermediary",
                    "updated_at",
                ]
            )

            self._log_status_change(
                user=user,
                action="accept",
                old_state=old_state,
            )

            self.send_accept_notifications(user)
            if self.accepted_by_logistic and self.accepted_by_carrier:
                from api.agreements.models import Agreement

                Agreement.get_or_create_from_offer(self)

    def _accept_case_customer_logistic(self, user):
        cargo = self.cargo

        # ✅ 1. Фиксируем OLD STATE ДО изменений
        old_state = {
            "accepted_by_customer": self.accepted_by_customer,
            "accepted_by_carrier": self.accepted_by_carrier,
            "accepted_by_logistic": self.accepted_by_logistic,
        }

        print("\n[MODEL CASE customer_logistic]")
        print("user.id =", user.id, "role =", user.role)
        print("cargo.customer_id =", cargo.customer_id)
        print("cargo.created_by_id =", cargo.created_by_id)
        print("offer.logistic_id =", self.logistic_id)
        print("offer.intermediary_id =", self.intermediary_id)
        print(
            "flags BEFORE:",
            "customer =",
            self.accepted_by_customer,
            "logistic =",
            self.accepted_by_logistic,
        )

        # ==========================================================
        # 🟢 КЕЙС 1: заказчик по ID (включая логиста-заказчика)
        # ==========================================================
        if user.id in (cargo.customer_id, cargo.created_by_id):
            print("✔ CUSTOMER SIDE ACCEPT (by id)")
            self.accepted_by_customer = True

            print(
                "flags AFTER:",
                "customer =",
                self.accepted_by_customer,
                "logistic =",
                self.accepted_by_logistic,
            )

            with transaction.atomic():
                print("→ SAVE OFFER")
                self.save(
                    update_fields=[
                        "accepted_by_customer",
                        "accepted_by_logistic",
                        "updated_at",
                    ]
                )

                # ✅ ЛОГ accept (ЭТОГО РАНЬШЕ НЕ ХВАТАЛО)
                self._log_status_change(
                    user=user,
                    action="accept",
                    old_state=old_state,
                )

                print("→ SEND NOTIFICATIONS")
                self.send_accept_notifications(user)

                if self.accepted_by_customer and self.accepted_by_logistic:
                    print("✅ HANDSHAKE TRUE → CREATE AGREEMENT")
                    from api.agreements.models import Agreement

                    Agreement.get_or_create_from_offer(self)
                else:
                    print("⏳ HANDSHAKE FALSE")

            return

        # ==========================================================
        # 🟢 КЕЙС 2: обычный CUSTOMER
        # ==========================================================
        if user.role == "CUSTOMER":
            print("✔ CUSTOMER ACCEPT")
            self.accepted_by_customer = True

        # ==========================================================
        # 🟢 КЕЙС 3: LOGISTIC-участник
        # ==========================================================
        elif user.role == "LOGISTIC" and user.id in (
            self.logistic_id,
            self.intermediary_id,
        ):
            print("✔ LOGISTIC ACCEPT")
            self.accepted_by_logistic = True

        else:
            print("❌ INVALID PARTICIPANT → PermissionDenied")
            raise PermissionDenied("Недопустимый участник для данного кейса")

        print(
            "flags AFTER:",
            "customer =",
            self.accepted_by_customer,
            "logistic =",
            self.accepted_by_logistic,
        )

        # ==========================================================
        # 🟢 ОБЩИЙ SAVE + LOG + NOTIFY
        # ==========================================================
        with transaction.atomic():
            print("→ SAVE OFFER")
            self.save(
                update_fields=[
                    "accepted_by_customer",
                    "accepted_by_logistic",
                    "updated_at",
                ]
            )

            # ✅ ЛОГ accept
            self._log_status_change(
                user=user,
                action="accept",
                old_state=old_state,
            )

            print("→ SEND NOTIFICATIONS")
            self.send_accept_notifications(user)

            if self.accepted_by_customer and self.accepted_by_logistic:
                print("✅ HANDSHAKE TRUE → CREATE AGREEMENT")
                from api.agreements.models import Agreement

                Agreement.get_or_create_from_offer(self)
            else:
                print("⏳ HANDSHAKE FALSE")

    def _accept_case_logistic_logistic(self, user):
        # ✅ 1. OLD STATE ДО ИЗМЕНЕНИЙ
        old_state = {
            "accepted_by_customer": self.accepted_by_customer,
            "accepted_by_carrier": self.accepted_by_carrier,
            "accepted_by_logistic": self.accepted_by_logistic,
        }

        # ✅ 2. БИЗНЕС-ЛОГИКА
        if user.role == "LOGISTIC":
            if user.id in (self.logistic_id, self.intermediary_id):
                self.accepted_by_logistic = True
            elif self.intermediary is None:
                self.accepted_by_logistic = True
                self.intermediary = user
            else:
                raise PermissionDenied("Логист не является участником этого оффера")
        else:
            raise PermissionDenied("Недопустимый участник для данного кейса")

        # ✅ 3. SAVE + LOG + NOTIFY + AGREEMENT
        with transaction.atomic():
            self.save(
                update_fields=[
                    "accepted_by_logistic",
                    "intermediary",
                    "updated_at",
                ]
            )

            # ✅ ОБЯЗАТЕЛЬНОЕ ЛОГИРОВАНИЕ ACCEPT
            self._log_status_change(
                user=user,
                action="accept",
                old_state=old_state,
            )

            self.send_accept_notifications(user)

            # ✅ создаём Agreement при handshake
            if self.accepted_by_logistic:
                from api.agreements.models import Agreement

                Agreement.get_or_create_from_offer(self)

    def get_response_status_for(self, user) -> str:
        """
        waiting — пользователь уже ответил, ждёт другую сторону
        action_required — пользователю нужно ответить
        rejected — оффер отклонён / неактивен
        counter — контр от любого другого участника
        """
        if not self.is_active:
            return "rejected"

        # 🔥 counter-статус — это состояние оффера, не пользователя
        if self.is_counter:
            return self.response_status or "counter"

        role = getattr(user, "role", None)

        if role == "CUSTOMER":
            return "waiting" if self.accepted_by_customer else "action_required"

        if role == "CARRIER":
            return "waiting" if self.accepted_by_carrier else "action_required"

        if role == "LOGISTIC":
            return "waiting" if self.accepted_by_logistic else "action_required"

        return "waiting"


class OfferStatusLog(models.Model):
    offer = models.ForeignKey(
        Offer,
        on_delete=models.CASCADE,
        related_name="status_logs",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    action = models.CharField(max_length=32)
    old_state = models.JSONField()
    new_state = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Offer#{self.offer_id} {self.action}"
