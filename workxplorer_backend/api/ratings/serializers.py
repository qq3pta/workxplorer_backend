from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from api.chat.serializers import build_user_avatar_url

from .models import UserRating

User = get_user_model()


class RatingUserDocumentSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    order_id = serializers.IntegerField(read_only=True)
    title = serializers.CharField(read_only=True)
    category = serializers.CharField(read_only=True)
    category_display = serializers.CharField(read_only=True)
    file = serializers.FileField(read_only=True)
    file_name = serializers.CharField(read_only=True, allow_null=True)
    file_size = serializers.IntegerField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)


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
    avatar = serializers.SerializerMethodField()

    phone = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)
    city = serializers.CharField(source="profile_city", read_only=True)

    avg_rating = serializers.FloatField(source="avg_rating_value", read_only=True)
    rating_count = serializers.IntegerField(source="rating_count_value", read_only=True)
    completed_orders = serializers.IntegerField(source="completed_orders_value", read_only=True)

    registered_at = serializers.DateTimeField(source="date_joined", read_only=True)
    country = serializers.CharField(source="profile.country", read_only=True)
    documents = serializers.SerializerMethodField()

    total_distance = serializers.SerializerMethodField()

    pie_chart = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "role",
            "company_name",
            "inn",
            "legal_address",
            "is_verified",
            "display_name",
            "avatar",
            "phone",
            "email",
            "city",
            "country",
            "avg_rating",
            "rating_count",
            "completed_orders",
            "total_distance",
            "registered_at",
            "documents",
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

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_avatar(self, obj):
        return build_user_avatar_url(obj, request=self.context.get("request"))

    @extend_schema_field(RatingUserDocumentSerializer(many=True))
    def get_documents(self, obj):
        from api.orders.models import OrderDocument

        documents = getattr(obj, "published_documents", None)
        if documents is None:
            documents = OrderDocument.objects.filter(uploaded_by=obj).order_by("-created_at")

        return [
            {
                "id": document.id,
                "order_id": document.order_id,
                "title": document.title,
                "category": document.category,
                "category_display": document.get_category_display(),
                "file": document.file.url if document.file else None,
                "file_name": document.file.name.rsplit("/", 1)[-1] if document.file else None,
                "file_size": self._get_document_file_size(document),
                "created_at": document.created_at,
            }
            for document in documents
        ]

    def _get_document_file_size(self, document):
        if not document.file:
            return None
        try:
            return int(document.file.size)
        except (FileNotFoundError, OSError):
            return None

    # -----------------------
    # KM суммарно для перевозчика
    # -----------------------
    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_total_distance(self, obj):
        if getattr(obj, "role", None) != "CARRIER":
            return None
        return int(getattr(obj, "total_distance_value", 0) or 0)

    # -----------------------
    # Piechart statistics
    # -----------------------
    @extend_schema_field(serializers.DictField(child=serializers.IntegerField()))
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
