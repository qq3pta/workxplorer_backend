from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field, inline_serializer
from rest_framework import serializers

from .models import Chat, ChatParticipant, Message

User = get_user_model()
ONLINE_WINDOW = timedelta(minutes=5)


def build_user_display_name(user) -> str:
    full_name = (user.get_full_name() or "").strip()
    return full_name or user.username or user.email or f"User#{user.id}"


def build_user_avatar_url(user, request=None):
    photo = getattr(user, "photo", None)
    if not photo:
        return None
    try:
        url = photo.url
    except Exception:
        return None
    if request:
        return request.build_absolute_uri(url)
    return url


def build_user_is_online(user) -> bool:
    last_seen = getattr(user, "last_seen", None)
    if not last_seen:
        return False
    return last_seen >= timezone.now() - ONLINE_WINDOW


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
        return chat


class GroupAddParticipantsSerializer(serializers.Serializer):
    participant_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=True,
        allow_empty=False,
    )

    def validate_participant_ids(self, value):
        deduped = list(dict.fromkeys(value))
        if len(deduped) > 10:
            raise serializers.ValidationError("Нельзя добавить больше 10 участников за раз.")
        return deduped


class GroupInviteDecisionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=("accept", "decline"))


class InviteLinkRequestSerializer(serializers.Serializer):
    expires_in_hours = serializers.IntegerField(min_value=48, max_value=48, default=48)


class InviteLinkResponseSerializer(serializers.Serializer):
    token = serializers.UUIDField()
    expires_at = serializers.DateTimeField()


class JoinByLinkSerializer(serializers.Serializer):
    token = serializers.UUIDField()


class UserPreviewSerializer(serializers.ModelSerializer):
    avatar = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()
    user_role = serializers.CharField(source="role", read_only=True)
    last_seen = serializers.DateTimeField(read_only=True)
    is_online = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "full_name", "avatar", "user_role", "last_seen", "is_online"]

    @extend_schema_field(serializers.CharField())
    def get_full_name(self, obj):
        return build_user_display_name(obj)

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_avatar(self, obj):
        return build_user_avatar_url(obj, request=self.context.get("request"))

    @extend_schema_field(serializers.BooleanField())
    def get_is_online(self, obj):
        return build_user_is_online(obj)


class UserSearchResultSerializer(UserPreviewSerializer):
    pass


class ChatInvitationItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    chat_type = serializers.CharField(default="invitation")
    title = serializers.CharField()
    display_title = serializers.CharField()
    participants_count = serializers.IntegerField()
    unread_count = serializers.IntegerField(default=0)
    last_message = serializers.JSONField(allow_null=True)
    last_message_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    invitation_group_id = serializers.IntegerField()
    invitation_group_title = serializers.CharField()
    invitation_participants_count = serializers.IntegerField()
    invited_by = UserPreviewSerializer(allow_null=True)
    invited_at = serializers.DateTimeField(allow_null=True)


class ChatMemberSerializer(UserPreviewSerializer):
    company_name = serializers.SerializerMethodField()

    class Meta(UserPreviewSerializer.Meta):
        fields = [*UserPreviewSerializer.Meta.fields, "company_name"]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_company_name(self, obj):
        return (obj.company_name or "").strip() or None


class ChatInfoSerializer(serializers.ModelSerializer):
    participants_count = serializers.IntegerField(source="participants.count", read_only=True)
    members = serializers.SerializerMethodField()
    display_title = serializers.SerializerMethodField()
    chat_avatar = serializers.SerializerMethodField()
    company_name = serializers.SerializerMethodField()
    user_last_seen = serializers.SerializerMethodField()
    user_is_online = serializers.SerializerMethodField()
    creator = serializers.SerializerMethodField()
    is_muted = serializers.SerializerMethodField()

    class Meta:
        model = Chat
        fields = [
            "id",
            "chat_type",
            "title",
            "display_title",
            "chat_avatar",
            "company_name",
            "user_last_seen",
            "user_is_online",
            "is_muted",
            "participants_count",
            "members",
            "creator",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(ChatMemberSerializer(many=True))
    def get_members(self, obj):
        participants = (
            obj.participants.filter(is_active=True)
            .select_related("user")
            .order_by("-is_admin", "user__first_name", "user__last_name", "user__username")
        )
        users = [participant.user for participant in participants]
        return ChatMemberSerializer(users, many=True, context=self.context).data

    def _viewer_user_id(self):
        request = self.context.get("request")
        if not request or not request.user or not request.user.is_authenticated:
            return None
        return request.user.id

    def _viewer_participant(self, obj):
        participant = getattr(obj, "_viewer_participant", None)
        if participant is not None:
            return participant
        user_id = self._viewer_user_id()
        if not user_id:
            return None
        return (
            obj.participants.filter(user_id=user_id, is_active=True).only("id", "is_muted").first()
        )

    def _other_user(self, obj):
        viewer_user_id = self._viewer_user_id()
        if obj.chat_type != Chat.ChatType.PERSONAL or not viewer_user_id:
            return None
        participant = (
            obj.participants.filter(is_active=True)
            .exclude(user_id=viewer_user_id)
            .select_related("user")
            .first()
        )
        return participant.user if participant else None

    @extend_schema_field(serializers.CharField())
    def get_display_title(self, obj):
        if obj.chat_type == Chat.ChatType.GROUP:
            return obj.title
        other_user = self._other_user(obj)
        if not other_user:
            return obj.title or "Личный чат"
        return build_user_display_name(other_user)

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_chat_avatar(self, obj):
        other_user = self._other_user(obj)
        if not other_user:
            return None
        return build_user_avatar_url(other_user, request=self.context.get("request"))

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_company_name(self, obj):
        other_user = self._other_user(obj)
        if not other_user:
            return None
        return (other_user.company_name or "").strip() or None

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_user_last_seen(self, obj):
        other_user = self._other_user(obj)
        if not other_user:
            return None
        return other_user.last_seen

    @extend_schema_field(serializers.BooleanField())
    def get_user_is_online(self, obj):
        other_user = self._other_user(obj)
        if not other_user:
            return False
        return build_user_is_online(other_user)

    @extend_schema_field(serializers.BooleanField())
    def get_is_muted(self, obj):
        participant = self._viewer_participant(obj)
        if not participant:
            return False
        return bool(participant.is_muted)

    @extend_schema_field(ChatMemberSerializer(allow_null=True))
    def get_creator(self, obj):
        if obj.chat_type != Chat.ChatType.GROUP or not obj.created_by:
            return None
        return ChatMemberSerializer(obj.created_by, context=self.context).data


class MessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.SerializerMethodField()
    attachment_url = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            "id",
            "chat",
            "sender",
            "sender_name",
            "text",
            "attachment_url",
            "attachment_name",
            "attachment_size",
            "attachment_content_type",
            "is_edited",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "chat",
            "sender",
            "sender_name",
            "is_edited",
            "attachment_name",
            "attachment_size",
            "attachment_content_type",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(serializers.CharField())
    def get_sender_name(self, obj):
        if not obj.sender:
            return "Удаленный пользователь"
        return build_user_display_name(obj.sender)

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_attachment_url(self, obj):
        if not obj.attachment:
            return None
        try:
            url = obj.attachment.url
        except Exception:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(url)
        return url


class MessageCreateSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=5000, required=False, allow_blank=True)
    file = serializers.FileField(required=False, allow_null=True, write_only=True)

    def validate_text(self, value):
        return value.strip()

    def validate(self, attrs):
        text = (attrs.get("text") or "").strip()
        file_obj = attrs.get("file")
        if not text and not file_obj:
            raise serializers.ValidationError("Нужно передать текст или файл.")
        attrs["text"] = text
        return attrs

    def create(self, validated_data):
        chat = self.context["chat"]
        user = self.context["request"].user
        file_obj = validated_data.get("file")
        attachment_name = ""
        attachment_size = None
        attachment_content_type = ""
        if file_obj:
            attachment_name = Path(file_obj.name).name
            attachment_size = getattr(file_obj, "size", None)
            attachment_content_type = getattr(file_obj, "content_type", "") or ""

        return Message.objects.create(
            chat=chat,
            sender=user,
            text=validated_data.get("text", ""),
            attachment=file_obj,
            attachment_name=attachment_name,
            attachment_size=attachment_size,
            attachment_content_type=attachment_content_type,
        )


class ChatListItemSerializer(serializers.ModelSerializer):
    participants_count = serializers.IntegerField(source="participants.count", read_only=True)
    unread_count = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    display_title = serializers.SerializerMethodField()
    chat_avatar = serializers.SerializerMethodField()
    company_name = serializers.SerializerMethodField()
    user_last_seen = serializers.SerializerMethodField()
    user_is_online = serializers.SerializerMethodField()
    is_muted = serializers.SerializerMethodField()

    class Meta:
        model = Chat
        fields = [
            "id",
            "chat_type",
            "title",
            "display_title",
            "chat_avatar",
            "company_name",
            "user_last_seen",
            "user_is_online",
            "is_muted",
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

    def _get_other_user(self, obj):
        participant = self._get_participant(obj)
        if not participant or obj.chat_type != Chat.ChatType.PERSONAL:
            return None
        other_participant = (
            obj.participants.filter(is_active=True)
            .exclude(user_id=participant.user_id)
            .select_related("user")
            .first()
        )
        return other_participant.user if other_participant else None

    @extend_schema_field(serializers.IntegerField())
    def get_unread_count(self, obj):
        participant = self._get_participant(obj)
        if not participant:
            return 0
        if participant.last_read_at:
            return (
                obj.messages.filter(created_at__gt=participant.last_read_at)
                .exclude(sender_id=participant.user_id)
                .count()
            )
        return obj.messages.exclude(sender_id=participant.user_id).count()

    @extend_schema_field(
        inline_serializer(
            "ChatLastMessagePreview",
            fields={
                "id": serializers.IntegerField(),
                "text": serializers.CharField(),
                "sender_id": serializers.IntegerField(allow_null=True),
                "sender_name": serializers.CharField(),
                "attachment_url": serializers.URLField(allow_null=True),
                "attachment_name": serializers.CharField(allow_blank=True),
                "created_at": serializers.DateTimeField(),
            },
        )
    )
    def get_last_message(self, obj):
        msg = obj.messages.select_related("sender").order_by("-created_at").first()
        if not msg:
            return None
        msg_data = MessageSerializer(instance=msg, context=self.context).data
        return {
            "id": msg.id,
            "text": msg.text,
            "sender_id": msg.sender_id,
            "sender_name": msg_data["sender_name"],
            "attachment_url": msg_data["attachment_url"],
            "attachment_name": msg_data["attachment_name"],
            "created_at": msg.created_at,
        }

    @extend_schema_field(serializers.CharField())
    def get_display_title(self, obj):
        if obj.chat_type == Chat.ChatType.GROUP:
            return obj.title
        other_user = self._get_other_user(obj)
        if not other_user:
            return obj.title or "Личный чат"
        return build_user_display_name(other_user)

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_chat_avatar(self, obj):
        other_user = self._get_other_user(obj)
        if not other_user:
            return None
        return build_user_avatar_url(other_user, request=self.context.get("request"))

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_company_name(self, obj):
        other_user = self._get_other_user(obj)
        if not other_user:
            return None
        return (other_user.company_name or "").strip() or None

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_user_last_seen(self, obj):
        other_user = self._get_other_user(obj)
        if not other_user:
            return None
        return other_user.last_seen

    @extend_schema_field(serializers.BooleanField())
    def get_user_is_online(self, obj):
        other_user = self._get_other_user(obj)
        if not other_user:
            return False
        return build_user_is_online(other_user)

    @extend_schema_field(serializers.BooleanField())
    def get_is_muted(self, obj):
        participant = self._get_participant(obj)
        if not participant:
            return False
        return bool(participant.is_muted)


class OpenPersonalChatSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(min_value=1)


class ChatMuteSerializer(serializers.Serializer):
    is_muted = serializers.BooleanField()


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
