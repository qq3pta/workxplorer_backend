from rest_framework import serializers
from .models import Cargo

class CargoCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cargo
        exclude = ("customer", "status", "created_at")

    def validate(self, data):
        if data.get("weight_kg") and data["weight_kg"] <= 0:
            raise serializers.ValidationError({"weight_kg": "Вес должен быть > 0"})
        if data.get("price") and data["price"] < 0:
            raise serializers.ValidationError({"price": "Цена не может быть отрицательной"})
        return data

class CargoListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cargo
        fields = "__all__"
        read_only_fields = ("customer", "status", "created_at")