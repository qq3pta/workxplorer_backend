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
        request = self.context["request"]
        user = request.user
        order = attrs["order"]
        rated_user = attrs["rated_user"]

        # 1. Определяем список всех участников, которым разрешено давать оценку
        # Используем set() для уникальности, хотя можно и list, но set безопаснее
        participants = {order.customer, order.carrier, order.logistic}
        allowed_users = {
            p for p in participants if p is not None
        }  # Отфильтровываем None, если логист не назначен

        # 2. Проверка: может ли текущий пользователь давать оценку? (Он должен быть участником)
        if user not in allowed_users:
            raise serializers.ValidationError(
                "Вы не участвуете в этом заказе."
            )  # ЭТО ИСПРАВЛЯЕТ ВАШУ ОШИБКУ

        # 3. Проверка: нельзя оценить самого себя
        if rated_user == user:
            raise serializers.ValidationError("Нельзя оценить самого себя.")

        # 4. Проверка: оцениваемый пользователь должен быть участником заказа
        # (Например, если Посредник оценивает Заказчика, Заказчик должен быть в заказе)
        if rated_user not in allowed_users:
            raise serializers.ValidationError("Пользователь не участвует в заказе.")

        # 5. Проверка: уникальность оценки
        if UserRating.objects.filter(rated_user=rated_user, order=order).exists():
            raise serializers.ValidationError("Пользователь уже был оценён в этом заказе.")

        return attrs

    def create(self, validated_data):
        validated_data["rated_by"] = self.context["request"].user
        return super().create(validated_data)


class RatingUserListSerializer(serializers.ModelSerializer):
    """
    Строка списка рейтингов (вкладки: Грузовладельцы / Логисты / Перевозчики).
    """

    display_name = serializers.SerializerMethodField()

    phone = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)
    city = serializers.CharField(source="profile_city", read_only=True)

    avg_rating = serializers.FloatField(source="avg_rating_value", read_only=True)
    rating_count = serializers.IntegerField(source="rating_count_value", read_only=True)
    completed_orders = serializers.IntegerField(source="completed_orders_value", read_only=True)

    registered_at = serializers.DateTimeField(source="date_joined", read_only=True)
    country = serializers.CharField(read_only=True)

    total_distance = serializers.SerializerMethodField()

    orders_stats = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "role",
            "company_name",
            "display_name",
            "phone",
            "email",
            "city",
            "country",
            "avg_rating",
            "rating_count",
            "completed_orders",
            "total_distance",
            "registered_at",
            "orders_stats",
        )
        read_only_fields = fields

    # -----------------------
    # ФИО вместо company_name
    # -----------------------
    def get_display_name(self, obj) -> str:
        full_name = obj.get_full_name() or getattr(obj, "name", "")
        if full_name:
            return full_name
        return obj.username or obj.email

    # -----------------------
    # KM суммарно для перевозчика
    # -----------------------
    def get_total_distance(self, obj):
        if getattr(obj, "role", None) != "CARRIER":
            return None
        return int(getattr(obj, "total_distance_value", 0) or 0)

    # -----------------------
    # Piechart statistics
    # -----------------------
    def get_orders_stats(self, obj):
        """
        Возвращает структуру вида:
        {
            "total": int,
            "completed": int,
            "in_progress": int,
            "queued": int,
            "excellent": int
        }
        """
        return {
            "total": int(getattr(obj, "orders_total_value", 0)),
            "completed": int(getattr(obj, "orders_completed_value", 0)),
            "in_progress": int(getattr(obj, "orders_in_progress_value", 0)),
            "queued": int(getattr(obj, "orders_queued_value", 0)),
            "excellent": int(getattr(obj, "orders_excellent_value", 0)),
        }
