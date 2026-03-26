from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers

from .models import Chat, ChatParticipant

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
        if len(deduped) > 100:
            raise serializers.ValidationError("Нельзя добавить больше 100 участников за раз.")
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
    expires_in_hours = serializers.IntegerField(min_value=1, max_value=24 * 30, default=24 * 7)


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
