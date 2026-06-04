from django.utils import timezone
from rest_framework import serializers

from .models import Notification, NotificationPreference, PushDevice


class NotificationSerializer(serializers.ModelSerializer):
    cargo_id = serializers.IntegerField(source="cargo.id", read_only=True)
    offer_id = serializers.IntegerField(source="offer.id", read_only=True)
    payload = serializers.DictField(required=False)
    navigation = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "type",
            "title",
            "message",
            "payload",
            "cargo_id",
            "offer_id",
            "navigation",
            "is_read",
            "created_at",
        ]

    def get_navigation(self, obj):
        from .services import build_notification_push_data

        return build_notification_push_data(
            notification=obj,
            notification_type=obj.type,
            title=obj.title,
            message=obj.message,
            payload=obj.payload,
            cargo=obj.cargo,
            offer=obj.offer,
        )


class MarkReadSerializer(serializers.Serializer):
    """
    Для отметки уведомления как прочитанного.
    """

    id = serializers.IntegerField()


class MarkAllReadSerializer(serializers.Serializer):
    pass


class PushDeviceSerializer(serializers.ModelSerializer):
    token = serializers.CharField(source="expo_push_token")

    class Meta:
        model = PushDevice
        fields = [
            "id",
            "token",
            "platform",
            "device_id",
            "is_active",
            "last_seen_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_active", "last_seen_at", "created_at", "updated_at"]

    def validate_platform(self, value):
        value = (value or PushDevice.Platform.UNKNOWN).lower()
        valid_values = {choice[0] for choice in PushDevice.Platform.choices}
        if value not in valid_values:
            return PushDevice.Platform.UNKNOWN
        return value

    def validate_token(self, value):
        token = (value or "").strip()
        if not token:
            raise serializers.ValidationError("Expo push token обязателен.")

        if not (token.startswith("ExponentPushToken[") or token.startswith("ExpoPushToken[")):
            raise serializers.ValidationError("Некорректный Expo push token.")

        return token

    def create(self, validated_data):
        request = self.context["request"]
        token = validated_data["expo_push_token"]
        defaults = {
            "user": request.user,
            "platform": validated_data.get("platform", PushDevice.Platform.UNKNOWN),
            "device_id": validated_data.get("device_id", ""),
            "is_active": True,
            "last_seen_at": timezone.now(),
            "disabled_at": None,
            "error": "",
        }
        device, _created = PushDevice.objects.update_or_create(
            expo_push_token=token,
            defaults=defaults,
        )
        return device


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = [
            "push_enabled",
            "chat_push_enabled",
            "order_push_enabled",
            "offer_push_enabled",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]
