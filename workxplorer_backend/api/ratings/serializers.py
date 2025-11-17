from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import UserRating

User = get_user_model()


class UserRatingSerializer(serializers.ModelSerializer):
    rated_by = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = UserRating
        fields = [
            "id",
            "rated_user",
            "rated_by",
            "order",
            "score",
            "comment",
            "created_at",
        ]
        read_only_fields = ["id", "rated_by", "created_at"]

    def validate(self, attrs):
        user = self.context["request"].user
        order = attrs["order"]

        if user not in [order.customer, order.carrier]:
            raise serializers.ValidationError("Вы не участвуете в этом заказе.")
        if attrs["rated_user"] == user:
            raise serializers.ValidationError("Нельзя оценить самого себя.")
        return attrs


class RatingUserListSerializer(serializers.ModelSerializer):
    """
    Строка для списка рейтинга (вкладки: Грузовладельцы / Логисты / Перевозчики).
    """

    display_name = serializers.SerializerMethodField()
    avg_rating = serializers.FloatField(read_only=True)
    rating_count = serializers.IntegerField(read_only=True)
    completed_orders = serializers.IntegerField(read_only=True)
    registered_at = serializers.DateTimeField(source="date_joined", read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "role",
            "company_name",
            "display_name",
            "avg_rating",
            "rating_count",
            "completed_orders",
            "registered_at",
        )
        read_only_fields = fields

    def get_display_name(self, obj):
        return obj.company_name or obj.username or obj.email
