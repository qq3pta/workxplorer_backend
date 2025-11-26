from rest_framework import serializers
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    cargo_id = serializers.IntegerField(source="cargo.id", read_only=True)
    offer_id = serializers.IntegerField(source="offer.id", read_only=True)
    payload = serializers.DictField(required=False)

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
            "is_read",
            "created_at",
        ]


class MarkReadSerializer(serializers.Serializer):
    """
    Для отметки уведомления как прочитанного.
    """

    id = serializers.IntegerField()
