from rest_framework import serializers


class DirectionSerializer(serializers.Serializer):
    id = serializers.CharField()
    origin = serializers.CharField()
    destination = serializers.CharField()
    load_date = serializers.DateField(allow_null=True)
    delivery_date = serializers.DateField(allow_null=True)
    price_value = serializers.FloatField()
    price_currency = serializers.CharField()
    shipments = serializers.IntegerField()
    weight = serializers.FloatField()
    time = serializers.FloatField()


class DirectionDetailSerializer(serializers.Serializer):
    id = serializers.CharField()
    origin_region = serializers.CharField()
    destination_region = serializers.CharField()
    shipments = serializers.IntegerField()
    weight = serializers.FloatField()
    price_value = serializers.FloatField()
    price_currency = serializers.CharField()
    bar_chart = serializers.DictField()
    pie_chart = serializers.DictField()


class BaseAnalyticsSerializer(serializers.Serializer):
    successful_deliveries = serializers.IntegerField()
    successful_deliveries_change = serializers.FloatField()
    distance_km = serializers.FloatField()
    deals_count = serializers.IntegerField()
    average_price_per_km = serializers.FloatField()
    average_price_per_km_change = serializers.FloatField()
    directions = DirectionSerializer(many=True)
    bar_chart = serializers.DictField()
    pie_chart = serializers.DictField()


class MyAnalyticsSerializer(BaseAnalyticsSerializer):
    registered_since = serializers.DateField()
    days_since_registered = serializers.IntegerField()
    rating = serializers.FloatField()


class GlobalAnalyticsSerializer(BaseAnalyticsSerializer):
    pass
