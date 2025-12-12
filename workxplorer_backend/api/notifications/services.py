from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.mail import send_mail
from firebase_admin import messaging

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
    Создаёт уведомление в БД + WebSocket + Email + Push.
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

    data = {
        "id": str(notif.id),
        "type": type,
        "title": title,
        "message": message or "",
        "cargo_id": str(cargo.id) if cargo else "",
        "offer_id": str(offer.id) if offer else "",
        "created_at": notif.created_at.isoformat(),
    }

    if payload:
        for k, v in payload.items():
            data[k] = str(v)

    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(f"user_{user.id}", {"type": "notify", "data": data})
    except Exception as e:
        print("WebSocket error:", e)

    if user.email:
        try:
            send_mail(
                subject=title,
                message=message or title,
                from_email="KAD-ONE <kad.noreply1@gmail.com>",
                recipient_list=[user.email],
                fail_silently=True,
            )
        except Exception as e:
            print("Email send error:", e)

    if getattr(user, "fcm_token", None):
        try:
            send_push(
                token=user.fcm_token,
                title=title,
                message=message,
                data=data,
            )
        except Exception as e:
            print("FCM send error:", e)

    return notif
