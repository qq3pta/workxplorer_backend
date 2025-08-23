from django.db.models import TextChoices

class TransportType(TextChoices):
    TENT   = "TENT",   "Тент"
    CONT   = "CONT",   "Контейнер"
    REEFER = "REEFER", "Рефрижератор"
    DUMP   = "DUMP",   "Самосвал"
    CARTR  = "CARTR",  "Автотранспортер"
    GRAIN  = "GRAIN",  "Зерновоз"
    CRANE  = "CRANE",  "Кран"
    LOG    = "LOG",    "Лесовоз"
    PICKUP = "PICKUP", "Пикап"
    CEM    = "CEM",    "Цементовоз"
    TANK   = "TANK",   "Автоцистерна"
    MEGA   = "MEGA",   "Мега фура"

class Currency(TextChoices):
    UZS = "UZS", "сум"
    KZT = "KZT", "тнг"
    RUB = "RUB", "руб"
    USD = "USD", "USD"
    EUR = "EUR", "EUR"

class ContactPref(TextChoices):
    EMAIL = "email", "Email"
    PHONE = "phone", "Телефон"
    BOTH  = "both",  "Оба"

class ModerationStatus(TextChoices):
    PENDING  = "pending",  "На модерации"
    APPROVED = "approved", "Одобрено"
    REJECTED = "rejected", "Отклонено"