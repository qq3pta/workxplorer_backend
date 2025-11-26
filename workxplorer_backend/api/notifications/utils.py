from django.db import models


class NotificationType(models.TextChoices):
    # --- Заявки ---
    ORDER_CREATED = "order_created", "Заявка успешно создана и в модерации"
    ORDER_PUBLISHED = "order_published", "Заявка прошла модерацию и опубликована"
    ORDER_REJECTED = "order_rejected", "Заявка не прошла модерацию"

    # --- Предложения ---
    OFFER_SENT = "offer_sent", "Предложение успешно отправлено"
    OFFER_RECEIVED = "offer_received", "Получено новое предложение"
    OFFER_ANSWER_RECEIVED = "offer_answer_received", "Получен ответ по предложению"
    OFFER_RECEIVED_FROM_CARRIER = (
        "offer_received_from_carrier",
        "Предложение получено от исполнителя",
    )
    OFFER_RECEIVED_FROM_CUSTOMER = (
        "offer_received_from_customer",
        "Предложение получено от заказчика",
    )

    # --- Ответы и коммуникация ---
    OFFER_MY_RESPONSE_SENT = "offer_my_response_sent", "Вы успешно ответили на предложение"
    OFFER_RESPONSE_TO_ME = "offer_response_to_me", "Ваше предложение получило ответ"

    # --- Сделки ---
    DEAL_CONFIRM_REQUIRED = "deal_confirm_required", "Вы согласны по цене, подтвердите сделку"
    DEAL_CONFIRM_REQUIRED_BY_OTHER = (
        "deal_confirm_required_by_other",
        "Заказчик принял вашу цену, подтвердите сделку",
    )
    DEAL_CONFIRMED_BY_OTHER = "deal_confirmed_by_other", "Другая сторона подтвердила сделку"
    DEAL_REJECTED_BY_OTHER = "deal_rejected_by_other", "Другая сторона отклонила сделку"
    DEAL_SUCCESS = "deal_success", "Сделка успешно совершена"

    # --- Статусы перевозки ---
    CARGO_STATUS_CHANGED = "cargo_status_changed", "Изменения статуса перевозки"
    DRIVER_STATUS_CHANGED = "driver_status_changed", "Изменение статуса водителя"

    # --- Документы ---
    DOCUMENT_ADDED = "document_added", "Добавлен новый документ"

    # --- Оплата ---
    PAYMENT_REQUIRED = "payment_required", "Перевозка завершена, прошла ли оплата?"

    # --- Рейтинг ---
    RATING_REQUIRED = "rating_required", "Перевозка завершена, установите рейтинг"
    RATING_CHANGED = "rating_changed", "Ваш рейтинг изменился"

    # --- Для перевозчика ---
    OFFER_FROM_CUSTOMER = "offer_from_customer", "Предложение получено от заказчика"
    OFFER_FROM_FORWARDER = "offer_from_forwarder", "Предложение получено от посредника"


NOTIFICATION_TYPES = {t.value: t.label for t in NotificationType}


def get_notification_title(type_key):
    """
    Возвращает человекочитаемое название по ключу,
    если ключ неизвестен — возвращает "Уведомление".
    """
    return NOTIFICATION_TYPES.get(type_key, "Уведомление")
