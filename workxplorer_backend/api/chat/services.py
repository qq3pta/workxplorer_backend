from .models import Chat, ChatParticipant


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
