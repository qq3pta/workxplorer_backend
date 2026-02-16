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

        # Проверяем, что order передан
        order = attrs.get("order") or (self.instance.order if self.instance else None)
        if not order:
            raise serializers.ValidationError({"order": "Order не найден или не передан"})

        # Проверяем, что оцениваемый пользователь передан
        rated_user = attrs.get("rated_user") or (
            self.instance.rated_user if self.instance else None
        )
        if not rated_user:
            raise serializers.ValidationError({"rated_user": "Оцениваемый пользователь не найден"})

        # Участники заказа (фильтруем None)
        participants = {p for p in [order.customer, order.carrier, order.logistic] if p}

        # Проверка: текущий пользователь — участник заказа
        if user not in participants:
            raise serializers.ValidationError("Вы не участвуете в этом заказе.")

        # Проверка: нельзя оценивать самого себя
        if rated_user == user:
            raise serializers.ValidationError("Нельзя оценить самого себя.")

        # Проверка: оцениваемый пользователь должен быть участником заказа
        if rated_user not in participants:
            raise serializers.ValidationError("Пользователь не участвует в заказе.")

        # Проверка уникальности: один рейтинг на одного пользователя в рамках заказа
        qs = UserRating.objects.filter(rated_user=rated_user, rated_by=user, order=order)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Вы уже оценивали этого пользователя в этом заказе.")

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
    country = serializers.CharField(source="profile.country", read_only=True)

    total_distance = serializers.SerializerMethodField()

    pie_chart = serializers.SerializerMethodField()

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
            "pie_chart",
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
    def get_pie_chart(self, obj):
        """
        Pie chart распределения заказов пользователя по статусам,
        включая cancelled, pending, delivered и т.д.
        """
        orders_qs = (
            obj.orders_as_customer.all() | obj.orders_as_carrier.all() | obj.logistic_orders.all()
        )

        statuses = ["no_driver", "pending", "in_process", "delivered", "canceled"]

        result = {status: 0 for status in statuses}

        for status in statuses:
            result[status] = orders_qs.filter(status=status).count()

        return result
