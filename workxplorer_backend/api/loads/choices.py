from django.db.models import TextChoices


class TransportType(TextChoices):
    TENT = "TENT", "Тент"
    CONT = "CONT", "Контейнер"
    REEFER = "REEFER", "Рефрижератор"
    DUMP = "DUMP", "Самосвал"
    CARTR = "CARTR", "Автотранспортер"
    GRAIN = "GRAIN", "Зерновоз"
    LOG = "LOG", "Лесовоз"
    PICKUP = "PICKUP", "Пикап"
    MEGA = "MEGA", "Мега фура"
    OTHER = "OTHER", "Другое"


class CargoCategory(TextChoices):
    FOOD = "FOOD", "Продукты питания"
    FMCG = "FMCG", "Повседневные товары"
    TEXTILE = "TEXTILE", "Текстиль"
    APPLIANCES = "APPLIANCES", "Бытовая техника"
    FURNITURE = "FURNITURE", "Мебель"
    BUILDING = "BUILDING", "Стройматериалы"
    METALLURGY = "METALLURGY", "Металлургия"
    SPARE_PARTS = "SPARE_PARTS", "Запчасти"
    PHARMA = "PHARMA", "Фармацевтика"
    CHEMICAL = "CHEMICAL", "Химическая промышленность"
    ROAD_CONSTRUCTION = "ROAD_CONSTRUCTION", "Дорожное строительство"
    MINERALS = "MINERALS", "Минералы"
    WASTE = "WASTE", "Отходы"
    CARS = "CARS", "Автомобили"
    OTHER = "OTHER", "Другое"


PUBLISH_DISABLED_TRANSPORT_TYPES = {
    TransportType.GRAIN,
    TransportType.PICKUP,
    TransportType.LOG,
}


TRANSPORT_TO_CARGO_CATEGORIES = {
    TransportType.TENT: (
        CargoCategory.FOOD,
        CargoCategory.FMCG,
        CargoCategory.TEXTILE,
        CargoCategory.APPLIANCES,
        CargoCategory.FURNITURE,
        CargoCategory.BUILDING,
        CargoCategory.METALLURGY,
        CargoCategory.SPARE_PARTS,
        CargoCategory.PHARMA,
        CargoCategory.CHEMICAL,
        CargoCategory.OTHER,
    ),
    TransportType.CONT: (
        CargoCategory.FOOD,
        CargoCategory.TEXTILE,
        CargoCategory.APPLIANCES,
        CargoCategory.FURNITURE,
        CargoCategory.BUILDING,
        CargoCategory.METALLURGY,
        CargoCategory.SPARE_PARTS,
        CargoCategory.PHARMA,
        CargoCategory.CHEMICAL,
        CargoCategory.OTHER,
    ),
    TransportType.REEFER: (
        CargoCategory.FOOD,
        CargoCategory.PHARMA,
        CargoCategory.OTHER,
    ),
    TransportType.DUMP: (
        CargoCategory.BUILDING,
        CargoCategory.ROAD_CONSTRUCTION,
        CargoCategory.METALLURGY,
        CargoCategory.MINERALS,
        CargoCategory.WASTE,
        CargoCategory.OTHER,
    ),
    TransportType.CARTR: (CargoCategory.CARS,),
    TransportType.MEGA: (
        CargoCategory.FOOD,
        CargoCategory.FMCG,
        CargoCategory.TEXTILE,
        CargoCategory.APPLIANCES,
        CargoCategory.FURNITURE,
        CargoCategory.BUILDING,
        CargoCategory.METALLURGY,
        CargoCategory.SPARE_PARTS,
        CargoCategory.PHARMA,
        CargoCategory.CHEMICAL,
        CargoCategory.OTHER,
    ),
    TransportType.OTHER: (CargoCategory.OTHER,),
    # Исторические типы сохраняем для обратной совместимости.
    TransportType.GRAIN: (CargoCategory.OTHER,),
    TransportType.PICKUP: (CargoCategory.OTHER,),
    TransportType.LOG: (CargoCategory.OTHER,),
}


def get_allowed_cargo_categories(transport_type: str | None) -> tuple[str, ...]:
    if not transport_type:
        return (CargoCategory.OTHER,)
    return TRANSPORT_TO_CARGO_CATEGORIES.get(transport_type, (CargoCategory.OTHER,))


class Currency(TextChoices):
    UZS = "UZS", "сум"
    KZT = "KZT", "тнг"
    RUB = "RUB", "руб"
    USD = "USD", "USD"
    EUR = "EUR", "EUR"


class ContactPref(TextChoices):
    EMAIL = "email", "Email"
    PHONE = "phone", "Телефон"
    BOTH = "both", "Оба"


class ModerationStatus(TextChoices):
    PENDING = "pending", "На модерации"
    APPROVED = "approved", "Одобрено"
    REJECTED = "rejected", "Отклонено"
