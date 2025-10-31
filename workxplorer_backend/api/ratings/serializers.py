from rest_framework import serializers

from .models import UserRating


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
        """Проверка: только участники заказа могут оценивать."""
        user = self.context["request"].user
        order = attrs["order"]

        if user not in [order.customer, order.carrier]:
            raise serializers.ValidationError("Вы не участвуете в этом заказе.")
        if attrs["rated_user"] == user:
            raise serializers.ValidationError("Нельзя оценить самого себя.")
        return attrs
