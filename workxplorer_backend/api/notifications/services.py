from datetime import timedelta

import requests
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import ExpoPushTicket, Notification, NotificationPreference, PushDevice

EXPO_PUSH_SEND_URL = "https://exp.host/--/api/v2/push/send"
EXPO_PUSH_RECEIPTS_URL = "https://exp.host/--/api/v2/push/getReceipts"
EXPO_PUSH_CHUNK_SIZE = 100

OFFER_NOTIFICATION_TYPES = {
    "offer_sent",
    "offer_received",
    "offer_answer_received",
    "offer_received_from_carrier",
    "offer_received_from_customer",
    "offer_received_from_logistic",
    "offer_my_response_sent",
    "offer_response_to_me",
    "offer_from_customer",
    "offer_from_forwarder",
    "deal_confirm_required",
    "deal_confirm_required_by_other",
    "deal_confirmed_by_other",
    "deal_rejected_by_other",
}

ORDER_NOTIFICATION_TYPES = {
    "deal_success",
    "cargo_status_changed",
    "driver_status_changed",
    "payment_required",
    "rating_required",
    "rating_received",
    "rating_sent",
    "rating_changed",
    "document_added",
}

LOAD_NOTIFICATION_TYPES = {
    "order_created",
    "order_published",
    "order_rejected",
}


def _expo_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    access_token = getattr(settings, "EXPO_PUSH_ACCESS_TOKEN", "")
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


def _chunks(items: list, size: int):
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _is_push_allowed(user, notification_type: str | None = None) -> bool:
    preferences, _created = NotificationPreference.objects.get_or_create(user=user)

    if not preferences.push_enabled:
        return False

    type_key = notification_type or ""
    if type_key.startswith("chat_") or type_key == "new_message":
        return preferences.chat_push_enabled

    if type_key.startswith("order_"):
        return preferences.order_push_enabled

    if type_key.startswith("offer_") or "invite" in type_key:
        return preferences.offer_push_enabled

    return True


def _normalize_push_data(data: dict | None) -> dict:
    normalized = {}
    for key, value in (data or {}).items():
        if value is None:
            continue
        normalized[str(key)] = str(value)
    return normalized


def _resolve_order_id(payload=None, cargo=None, offer=None) -> int | None:
    payload = payload or {}

    raw_order_id = payload.get("order_id") or payload.get("orderId")
    if raw_order_id:
        value = str(raw_order_id).replace("order_", "")
        if value.isdigit():
            return int(value)

    if offer:
        order = getattr(offer, "order", None)
        if order:
            return order.id

    if cargo:
        order = getattr(cargo, "orders", None)
        if order is not None and hasattr(order, "first"):
            order_obj = order.first()
            if order_obj:
                return order_obj.id

    return None


def _navigation_for_type(notification_type: str, *, order_id=None, cargo_id=None, offer_id=None):
    data = {
        "screen": "Notifications",
        "route": "/notifications",
        "entity_type": "notification",
        "entity_id": "",
    }

    if notification_type in LOAD_NOTIFICATION_TYPES and cargo_id:
        data.update(
            {
                "screen": "CargoDetail",
                "route": f"/loads/{cargo_id}",
                "entity_type": "cargo",
                "entity_id": str(cargo_id),
            }
        )
        return data

    if notification_type in OFFER_NOTIFICATION_TYPES and offer_id:
        data.update(
            {
                "screen": "OfferDetail",
                "route": f"/offers/{offer_id}",
                "entity_type": "offer",
                "entity_id": str(offer_id),
            }
        )
        return data

    if notification_type in ORDER_NOTIFICATION_TYPES and order_id:
        tab = ""
        if notification_type == "payment_required":
            tab = "payment"
        elif notification_type == "document_added":
            tab = "documents"
        elif notification_type in {"driver_status_changed", "cargo_status_changed"}:
            tab = "tracking"
        elif notification_type in {"rating_required", "rating_received", "rating_sent"}:
            tab = "details"

        route = f"/orders/{order_id}"
        if tab:
            route = f"{route}?tab={tab}"

        data.update(
            {
                "screen": "OrderDetail",
                "route": route,
                "entity_type": "order",
                "entity_id": str(order_id),
                "tab": tab,
            }
        )
        return data

    if order_id:
        data.update(
            {
                "screen": "OrderDetail",
                "route": f"/orders/{order_id}",
                "entity_type": "order",
                "entity_id": str(order_id),
            }
        )
    elif offer_id:
        data.update(
            {
                "screen": "OfferDetail",
                "route": f"/offers/{offer_id}",
                "entity_type": "offer",
                "entity_id": str(offer_id),
            }
        )
    elif cargo_id:
        data.update(
            {
                "screen": "CargoDetail",
                "route": f"/loads/{cargo_id}",
                "entity_type": "cargo",
                "entity_id": str(cargo_id),
            }
        )

    return data


def build_notification_push_data(
    *,
    notification: Notification,
    notification_type: str,
    title: str,
    message: str = "",
    payload=None,
    cargo=None,
    offer=None,
) -> dict:
    payload = payload or {}
    cargo_id = cargo.id if cargo else payload.get("cargo_id")
    offer_id = offer.id if offer else payload.get("offer_id")
    order_id = _resolve_order_id(payload=payload, cargo=cargo, offer=offer)

    data = {
        "id": str(notification.id),
        "notification_id": str(notification.id),
        "event": notification_type,
        "type": notification_type,
        "title": title,
        "message": message or "",
        "cargo_id": str(cargo_id) if cargo_id else "",
        "offer_id": str(offer_id) if offer_id else "",
        "order_id": str(order_id) if order_id else "",
        "orderId": f"order_{order_id}" if order_id else "",
        "created_at": notification.created_at.isoformat(),
    }
    data.update(
        _navigation_for_type(
            notification_type,
            order_id=order_id,
            cargo_id=cargo_id,
            offer_id=offer_id,
        )
    )

    for key, value in payload.items():
        data[key] = value

    return data


def _disable_device_if_needed(device: PushDevice, details: dict | None, message: str = "") -> None:
    error = (details or {}).get("error")
    if error == "DeviceNotRegistered":
        device.disable(message or error)


def send_expo_push_to_user(
    *,
    user,
    title: str,
    message: str = "",
    data: dict | None = None,
    notification: Notification | None = None,
    notification_type: str | None = None,
) -> list[ExpoPushTicket]:
    if not user or not getattr(user, "id", None):
        return []

    if not _is_push_allowed(user, notification_type):
        return []

    title = (title or "").strip() or "Уведомление"
    message = (message or "").strip()
    push_data = _normalize_push_data(data)

    devices = list(
        PushDevice.objects.filter(user=user, is_active=True).only(
            "id",
            "expo_push_token",
            "is_active",
        )
    )
    if not devices:
        return []

    created_tickets = []
    for device_chunk in _chunks(devices, EXPO_PUSH_CHUNK_SIZE):
        messages = [
            {
                "to": device.expo_push_token,
                "title": title,
                "body": message or title,
                "data": push_data,
                "sound": "default",
                "priority": "high",
            }
            for device in device_chunk
        ]

        try:
            response = requests.post(
                EXPO_PUSH_SEND_URL,
                json=messages,
                headers=_expo_headers(),
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            print("Expo push send error:", exc)
            continue

        ticket_payloads = payload.get("data") or []
        if isinstance(ticket_payloads, dict):
            ticket_payloads = [ticket_payloads]

        for device, ticket_payload in zip(device_chunk, ticket_payloads, strict=False):
            status = ticket_payload.get("status", "")
            details = ticket_payload.get("details")
            ticket = ExpoPushTicket.objects.create(
                device=device,
                notification=notification,
                ticket_id=ticket_payload.get("id", ""),
                status=status,
                message=ticket_payload.get("message", ""),
                details=details,
            )
            created_tickets.append(ticket)

            if status == "error":
                _disable_device_if_needed(device, details, ticket.message)

    return created_tickets


def check_expo_push_receipts(limit: int = 300) -> int:
    tickets = list(
        ExpoPushTicket.objects.select_related("device")
        .filter(
            ticket_id__gt="",
            receipt_status="",
            created_at__gte=timezone.now() - timedelta(days=1),
        )
        .order_by("created_at")[:limit]
    )
    if not tickets:
        return 0

    checked_count = 0
    ticket_by_id = {ticket.ticket_id: ticket for ticket in tickets}

    for ticket_id_chunk in _chunks(list(ticket_by_id.keys()), EXPO_PUSH_CHUNK_SIZE):
        try:
            response = requests.post(
                EXPO_PUSH_RECEIPTS_URL,
                json={"ids": ticket_id_chunk},
                headers=_expo_headers(),
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            print("Expo receipt check error:", exc)
            continue

        receipts = payload.get("data") or {}
        for ticket_id, receipt in receipts.items():
            ticket = ticket_by_id.get(ticket_id)
            if not ticket:
                continue

            ticket.receipt_status = receipt.get("status", "")
            ticket.receipt_message = receipt.get("message", "")
            ticket.receipt_details = receipt.get("details")
            ticket.checked_at = timezone.now()
            ticket.save(
                update_fields=[
                    "receipt_status",
                    "receipt_message",
                    "receipt_details",
                    "checked_at",
                ]
            )
            checked_count += 1

            if ticket.receipt_status == "error":
                _disable_device_if_needed(
                    ticket.device,
                    ticket.receipt_details,
                    ticket.receipt_message,
                )

    return checked_count


def send_push(token: str, title: str, message: str, data=None):
    """Совместимость со старым вызовом: отправка одиночного Expo push."""
    if not token:
        return

    title = (title or "").strip()
    message = (message or "").strip()

    try:
        response = requests.post(
            EXPO_PUSH_SEND_URL,
            json={
                "to": token,
                "title": title,
                "body": message or title,
                "data": _normalize_push_data(data),
                "sound": "default",
                "priority": "high",
            },
            headers=_expo_headers(),
            timeout=10,
        )
        response.raise_for_status()
    except Exception as e:
        print("Expo push error:", e)


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

    data = build_notification_push_data(
        notification=notif,
        notification_type=type,
        title=title,
        message=message,
        payload=payload,
        cargo=cargo,
        offer=offer,
    )

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

    try:
        send_expo_push_to_user(
            user=user,
            title=title,
            message=message,
            data=data,
            notification=notif,
            notification_type=type,
        )
    except Exception as e:
        print("Expo push send error:", e)

    return notif
