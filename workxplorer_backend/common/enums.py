from django.db import models
from django.utils.translation import gettext_lazy as _

class Role(models.TextChoices):
    LOGISTIC = "LOGISTIC", _("Логист")
    CUSTOMER = "CUSTOMER", _("Заказчик")
    CARRIER  = "CARRIER",  _("Перевозчик")

class TransportType(models.TextChoices):
    TENT    = "TENT",      _("Тент")
    CONTAINER = "CONTAINER", _("Контейнеровоз")
    REEFER  = "REEFER",    _("Рефрижератор")
    DUMP    = "DUMP",      _("Самосвал")
    CAR_CARRIER = "CAR_CARRIER", _("Автовоз")
    GRAIN   = "GRAIN",     _("Зерновоз")
    CRANE   = "CRANE",     _("Манипулятор/Кран")
    TIMBER  = "TIMBER",    _("Лесовоз")
    PICKUP  = "PICKUP",    _("Пикап")
    CEMENT  = "CEMENT",    _("Цементовоз")
    TANKER  = "TANKER",    _("Цистерна")
    MEGA    = "MEGA",      _("Мега")

class Currency(models.TextChoices):
    UZS = "UZS", _("Сум")
    KZT = "KZT", _("Тенге")
    RUB = "RUB", _("Рубль")
    USD = "USD", _("Доллар")
    EUR = "EUR", _("Евро")

class DocumentCategory(models.TextChoices):
    LICENSE = "LICENSE", _("Лицензия")
    DRIVER  = "DRIVER",  _("Водитель")
    CONTRACT= "CONTRACT",_("Договор")
    LOAD    = "LOAD",    _("Погрузка")
    UNLOAD  = "UNLOAD",  _("Выгрузка")
    EXTRA   = "EXTRA",   _("Другое")