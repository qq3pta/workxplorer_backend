from __future__ import annotations

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from common.ws_utils import to_ws_safe

from .models import Chat, ChatParticipant, Message

ROLE_DEFAULT_GROUP_TITLES = {
    "LOGISTIC": "Общий с логистами",
    "CARRIER": "Общий с перевозчиками",
    "CUSTOMER": "Общий с заказчиками",
}


def user_is_chat_participant(chat: Chat, user_id: int) -> bool:
    return ChatParticipant.objects.filter(chat=chat, user_id=user_id, is_active=True).exists()


def user_can_manage_group(chat: Chat, user_id: int) -> bool:
    if chat.chat_type != Chat.ChatType.GROUP:
        return False

    if chat.created_by_id == user_id:
        return True

    return ChatParticipant.objects.filter(
        chat=chat,
        user_id=user_id,
        is_active=True,
        is_admin=True,
    ).exists()


def ws_user_group(user_id: int) -> str:
    return f"chat_user_{user_id}"


def ws_chat_group(chat_id: int) -> str:
    return f"chat_{chat_id}"


def _ws_send(group_name: str, data: dict) -> None:
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": "chat_event",
            "data": to_ws_safe(data),
        },
    )


def _message_payload(message: Message) -> dict:
    sender_name = "Удаленный пользователь"
    if message.sender:
        sender_name = (
            (message.sender.get_full_name() or "").strip()
            or message.sender.username
            or message.sender.email
            or f"User#{message.sender_id}"
        )

    attachment_url = None
    if message.attachment:
        try:
            attachment_url = message.attachment.url
        except Exception:
            attachment_url = None

    return {
        "id": message.id,
        "chat": message.chat_id,
        "sender": message.sender_id,
        "sender_name": sender_name,
        "text": message.text,
        "attachment_url": attachment_url,
        "attachment_name": message.attachment_name,
        "attachment_size": message.attachment_size,
        "attachment_content_type": message.attachment_content_type,
        "is_edited": message.is_edited,
        "created_at": message.created_at,
        "updated_at": message.updated_at,
    }


def _chat_payload(chat: Chat) -> dict:
    return {
        "id": chat.id,
        "chat_type": chat.chat_type,
        "title": chat.title,
        "last_message_at": chat.last_message_at,
        "created_at": chat.created_at,
    }


def _get_or_create_default_role_chat(role: str) -> Chat | None:
    title = ROLE_DEFAULT_GROUP_TITLES.get(role)
    if not title:
        return None

    existing = (
        Chat.objects.filter(
            chat_type=Chat.ChatType.GROUP,
            title=title,
            created_by__isnull=True,
        )
        .order_by("id")
        .first()
    )
    if existing:
        return existing

    return Chat.objects.create(
        chat_type=Chat.ChatType.GROUP,
        title=title,
        created_by=None,
        allow_join_by_link=False,
    )


def sync_user_default_role_chat(user, *, emit_events: bool = False) -> Chat | None:
    if not user or not getattr(user, "id", None):
        return None

    role = getattr(user, "role", None)
    if role not in ROLE_DEFAULT_GROUP_TITLES:
        return None

    target_chat = _get_or_create_default_role_chat(role)
    if not target_chat:
        return None

    participant, created = ChatParticipant.objects.get_or_create(
        chat=target_chat,
        user=user,
        defaults={"is_active": True, "is_admin": False},
    )
    became_active = False
    if not created and not participant.is_active:
        participant.is_active = True
        participant.save(update_fields=["is_active"])
        became_active = True

    other_titles = [title for key, title in ROLE_DEFAULT_GROUP_TITLES.items() if key != role]
    if other_titles:
        ChatParticipant.objects.filter(
            user=user,
            chat__chat_type=Chat.ChatType.GROUP,
            chat__title__in=other_titles,
            chat__created_by__isnull=True,
            is_active=True,
        ).update(is_active=False)

    if emit_events and (created or became_active):
        emit_added_to_group(target_chat, [user.id], added_by_id=None)

    return target_chat


def emit_new_message(message: Message) -> None:
    payload = _message_payload(message)

    # Live update for opened chat.
    _ws_send(
        ws_chat_group(message.chat_id),
        {
            "event": "new_message",
            "chat_id": message.chat_id,
            "message": payload,
        },
    )

    participants = ChatParticipant.objects.filter(chat_id=message.chat_id, is_active=True)
    for participant in participants:
        unread_count = (
            Message.objects.filter(chat_id=message.chat_id, created_at__gt=participant.last_read_at)
            .exclude(sender_id=participant.user_id)
            .count()
            if participant.last_read_at
            else Message.objects.filter(chat_id=message.chat_id)
            .exclude(sender_id=participant.user_id)
            .count()
        )

        _ws_send(
            ws_user_group(participant.user_id),
            {
                "event": "chat_list_updated",
                "chat": _chat_payload(message.chat),
                "last_message": payload,
                "unread_count": unread_count,
            },
        )

        if participant.user_id != message.sender_id:
            _ws_send(
                ws_user_group(participant.user_id),
                {
                    "event": "new_person_message",
                    "chat_id": message.chat_id,
                    "sender_id": message.sender_id,
                    "sender_name": payload["sender_name"],
                    "message_id": message.id,
                },
            )


def emit_added_to_group(chat: Chat, user_ids: list[int], added_by_id: int | None = None) -> None:
    for user_id in user_ids:
        _ws_send(
            ws_user_group(user_id),
            {
                "event": "added_to_group",
                "chat": _chat_payload(chat),
                "added_by_id": added_by_id,
            },
        )


def emit_member_joined(chat: Chat, user_id: int) -> None:
    _ws_send(
        ws_chat_group(chat.id),
        {
            "event": "member_joined",
            "chat_id": chat.id,
            "user_id": user_id,
        },
    )


def emit_message_read(chat_id: int, user_id: int, last_read_at) -> None:
    _ws_send(
        ws_chat_group(chat_id),
        {
            "event": "message_read",
            "chat_id": chat_id,
            "user_id": user_id,
            "last_read_at": last_read_at,
        },
    )


def emit_member_left(chat_id: int, user_id: int) -> None:
    _ws_send(
        ws_chat_group(chat_id),
        {
            "event": "member_left",
            "chat_id": chat_id,
            "user_id": user_id,
        },
    )


def emit_chat_removed(user_id: int, chat_id: int, reason: str) -> None:
    _ws_send(
        ws_user_group(user_id),
        {
            "event": "chat_removed",
            "chat_id": chat_id,
            "reason": reason,
        },
    )


def emit_group_deleted(user_ids: list[int], chat_id: int, title: str, deleted_by_id: int) -> None:
    for user_id in user_ids:
        _ws_send(
            ws_user_group(user_id),
            {
                "event": "group_deleted",
                "chat_id": chat_id,
                "title": title,
                "deleted_by_id": deleted_by_id,
            },
        )


def emit_group_invite_request(
    chat: Chat,
    user_ids: list[int],
    invited_by_id: int,
    invited_by_name: str = "",
) -> None:
    participants_count = ChatParticipant.objects.filter(chat=chat, is_active=True).count()
    for user_id in user_ids:
        _ws_send(
            ws_user_group(user_id),
            {
                "event": "group_invite_request",
                "chat_type": "invitation",
                "group_id": chat.id,
                "group_title": chat.title,
                "participants_count": participants_count,
                "invited_by_id": invited_by_id,
                "invited_by_name": invited_by_name,
                "chat": _chat_payload(chat),
            },
        )


def emit_message_deleted(chat_id: int, message_id: int, deleted_by_id: int) -> None:
    _ws_send(
        ws_chat_group(chat_id),
        {
            "event": "message_deleted",
            "chat_id": chat_id,
            "message_id": message_id,
            "deleted_by_id": deleted_by_id,
        },
    )


def emit_member_kicked(chat_id: int, user_id: int, kicked_by_id: int) -> None:
    _ws_send(
        ws_chat_group(chat_id),
        {
            "event": "member_kicked",
            "chat_id": chat_id,
            "user_id": user_id,
            "kicked_by_id": kicked_by_id,
        },
    )
