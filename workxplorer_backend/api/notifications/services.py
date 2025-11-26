from firebase_admin import messaging
from django.conf import settings
from .models import Notification


def send_push(token: str, title: str, message: str, data=None):
    """Отправка FCM push."""
    if not token:
        return

    title = (title or "").strip()
    message = (message or "").strip()

    try:
        msg = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=message,
            ),
            data=data or {},
            token=token,
        )
        messaging.send(msg)
    except Exception as e:
        print("FCM error:", e)


def notify(user, type: str, title: str, message: str = "", payload=None, cargo=None, offer=None):
    """
    Создаёт уведомление в БД + отправляет push при наличии токена.
    """

    notif = Notification.objects.create(
        user=user,
        type=type,
        title=title,
        message=message,
        payload=payload,
        cargo=cargo,
        offer=offer,
    )

    # ---- Подготовка data ----
    data = {
        "id": str(notif.id),
        "type": type,
        "cargo_id": str(cargo.id) if cargo else "",
        "offer_id": str(offer.id) if offer else "",
    }

    # Все значения payload → str
    for k, v in (payload or {}).items():
        data[k] = str(v)

    # ---- Push ----
    if getattr(user, "fcm_token", None):
        send_push(
            token=user.fcm_token,
            title=title,
            message=message,
            data=data,
        )

    return notif
