from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers

from .models import Chat, ChatParticipant, Message

User = get_user_model()


class ChatSummarySerializer(serializers.ModelSerializer):
    participants_count = serializers.IntegerField(source="participants.count", read_only=True)

    class Meta:
        model = Chat
        fields = [
            "id",
            "chat_type",
            "title",
            "allow_join_by_link",
            "invite_token",
            "invite_expires_at",
            "participants_count",
            "last_message_at",
            "created_at",
        ]
        read_only_fields = fields


class GroupCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    participant_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
    )
    share_link_enabled = serializers.BooleanField(default=False)

    def validate_participant_ids(self, value):
        # De-duplicate while preserving order.
        deduped = list(dict.fromkeys(value))
        if len(deduped) > 10:
            raise serializers.ValidationError("Нельзя добавить больше 10 участников за раз.")
        return deduped

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        user = request.user
        participant_ids = validated_data.get("participant_ids", [])
        share_link_enabled = validated_data.get("share_link_enabled", False)

        users_qs = User.objects.filter(id__in=participant_ids).exclude(id=user.id)
        found_ids = set(users_qs.values_list("id", flat=True))
        missing = [uid for uid in participant_ids if uid not in found_ids]
        if missing:
            raise serializers.ValidationError(
                {"participant_ids": f"Пользователи не найдены: {missing}"}
            )

        chat = Chat.objects.create(
            chat_type=Chat.ChatType.GROUP,
            title=validated_data["title"].strip(),
            created_by=user,
            allow_join_by_link=share_link_enabled,
        )
        if share_link_enabled:
            chat.refresh_invite()

        ChatParticipant.objects.create(chat=chat, user=user, is_admin=True)
        ChatParticipant.objects.bulk_create(
            [ChatParticipant(chat=chat, user=member) for member in users_qs],
            ignore_conflicts=True,
        )
        return chat


class InviteLinkRequestSerializer(serializers.Serializer):
    expires_in_hours = serializers.IntegerField(min_value=48, max_value=48, default=48)


class InviteLinkResponseSerializer(serializers.Serializer):
    token = serializers.UUIDField()
    expires_at = serializers.DateTimeField()


class JoinByLinkSerializer(serializers.Serializer):
    token = serializers.UUIDField()


class UserSearchResultSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "full_name", "username", "email", "phone", "company_name"]

    def get_full_name(self, obj):
        full_name = (obj.get_full_name() or "").strip()
        return full_name or obj.username or obj.email or f"User#{obj.id}"


class MessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ["id", "chat", "sender", "sender_name", "text", "is_edited", "created_at", "updated_at"]
        read_only_fields = ["id", "chat", "sender", "sender_name", "is_edited", "created_at", "updated_at"]

    def get_sender_name(self, obj):
        if not obj.sender:
            return "Удаленный пользователь"
        full_name = (obj.sender.get_full_name() or "").strip()
        return full_name or obj.sender.username or obj.sender.email or f"User#{obj.sender_id}"


class MessageCreateSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=5000)

    def validate_text(self, value):
        text = value.strip()
        if not text:
            raise serializers.ValidationError("Сообщение не может быть пустым.")
        return text

    def create(self, validated_data):
        chat = self.context["chat"]
        user = self.context["request"].user
        return Message.objects.create(chat=chat, sender=user, text=validated_data["text"])


class ChatListItemSerializer(serializers.ModelSerializer):
    participants_count = serializers.IntegerField(source="participants.count", read_only=True)
    unread_count = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = Chat
        fields = [
            "id",
            "chat_type",
            "title",
            "participants_count",
            "unread_count",
            "last_message",
            "last_message_at",
            "created_at",
        ]

    def _get_participant(self, obj):
        request = self.context.get("request")
        if not request or not request.user or not request.user.is_authenticated:
            return None
        return getattr(obj, "_viewer_participant", None)

    def get_unread_count(self, obj):
        participant = self._get_participant(obj)
        if not participant:
            return 0
        if participant.last_read_at:
            return obj.messages.filter(created_at__gt=participant.last_read_at).exclude(
                sender_id=participant.user_id
            ).count()
        return obj.messages.exclude(sender_id=participant.user_id).count()

    def get_last_message(self, obj):
        msg = obj.messages.select_related("sender").order_by("-created_at").first()
        if not msg:
            return None
        msg_data = MessageSerializer(instance=msg).data
        return {
            "id": msg.id,
            "text": msg.text,
            "sender_id": msg.sender_id,
            "sender_name": msg_data["sender_name"],
            "created_at": msg.created_at,
        }


class MarkReadSerializer(serializers.Serializer):
    up_to_message_id = serializers.IntegerField(required=False, min_value=1)

    def save(self, **kwargs):
        chat = self.context["chat"]
        participant = self.context["participant"]
        message_id = self.validated_data.get("up_to_message_id")

        qs = Message.objects.filter(chat=chat)
        if message_id:
            qs = qs.filter(id__lte=message_id)
        latest = qs.order_by("-created_at").first()

        if latest:
            participant.last_read_at = latest.created_at
            participant.save(update_fields=["last_read_at"])

        return {"last_read_at": participant.last_read_at}
