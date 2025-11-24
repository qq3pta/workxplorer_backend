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

        # Проверка: участвует ли пользователь в заказе
        if user not in [order.customer, order.carrier]:
            raise serializers.ValidationError("Вы не участвуете в этом заказе.")

        # Проверка: нельзя оценить самого себя
        if attrs["rated_user"] == user:
            raise serializers.ValidationError("Нельзя оценить самого себя.")

        return attrs


class RatingUserListSerializer(serializers.ModelSerializer):
    """
    Строка списка рейтингов (вкладки: Грузовладельцы / Логисты / Перевозчики).
    """

    display_name = serializers.SerializerMethodField()

    # приходят из аннотаций:
    avg_rating = serializers.FloatField(read_only=True)
    rating_count = serializers.IntegerField(read_only=True)
    completed_orders = serializers.IntegerField(read_only=True)

    # показываем дату регистрации
    registered_at = serializers.DateTimeField(source="date_joined", read_only=True)

    # страна пользователя
    country = serializers.CharField(read_only=True)

    # только для перевозчиков
    total_distance = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "role",
            "company_name",
            "display_name",
            "country",
            "avg_rating",
            "rating_count",
            "completed_orders",
            "total_distance",
            "registered_at",
        )
        read_only_fields = fields

    def get_display_name(self, obj):
        """
        Отображаем:
        - company_name (если есть)
        - или username
        - или email
        """
        return obj.company_name or obj.username or obj.email

    def get_total_distance(self, obj):
        """
        total_distance приходит как аннотация.
        Для ролей LOGISTIC / CUSTOMER не показываем.
        """
        if getattr(obj, "role", None) != "CARRIER":
            return None

        return getattr(obj, "total_distance", 0)
