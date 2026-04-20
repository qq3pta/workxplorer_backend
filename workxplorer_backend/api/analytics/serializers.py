from rest_framework import serializers


class DirectionSerializer(serializers.Serializer):
    id = serializers.CharField()
    origin = serializers.CharField()
    destination = serializers.CharField()
    load_date = serializers.DateField(allow_null=True)
    delivery_date = serializers.DateField(allow_null=True)
    price_value = serializers.FloatField()
    min_price = serializers.FloatField()
    max_price = serializers.FloatField()
    price_currency = serializers.CharField()
    shipments = serializers.IntegerField()
    weight = serializers.FloatField()
    time = serializers.CharField()


class BarChartSerializer(serializers.Serializer):
    labels = serializers.ListField(child=serializers.CharField())
    given = serializers.ListField(child=serializers.FloatField())
    received = serializers.ListField(child=serializers.FloatField())
    earned = serializers.ListField(child=serializers.FloatField())


class PieChartSerializer(serializers.Serializer):
    in_search = serializers.IntegerField()
    in_process = serializers.IntegerField()
    successful = serializers.IntegerField()
    cancelled = serializers.IntegerField()
    total = serializers.IntegerField()


class PieSliceSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()
    shipments = serializers.IntegerField()
    percent = serializers.FloatField()


class PieChartsSerializer(serializers.Serializer):
    year = serializers.IntegerField()
    total_shipments = serializers.IntegerField()
    by_cargo_category = PieSliceSerializer(many=True)
    by_transport_type = PieSliceSerializer(many=True)


class PriceCurveSerializer(serializers.Serializer):
    avg = serializers.ListField(child=serializers.FloatField())
    min = serializers.ListField(child=serializers.FloatField())
    max = serializers.ListField(child=serializers.FloatField())


class PricesChartSerializer(serializers.Serializer):
    currency = serializers.CharField()
    customer_to_intermediary = PriceCurveSerializer()
    carrier_earnings = PriceCurveSerializer()


class SeasonChartSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=["shipments", "prices"])
    year = serializers.IntegerField()
    labels = serializers.ListField(child=serializers.CharField())
    shipments = serializers.ListField(child=serializers.IntegerField())
    prices = PricesChartSerializer()


class CountryDirectionSerializer(serializers.Serializer):
    id = serializers.CharField()
    origin = serializers.CharField()
    destination = serializers.CharField()
    price_value = serializers.FloatField()
    price_currency = serializers.CharField()
    shipments = serializers.IntegerField()
    weight = serializers.FloatField()
    time = serializers.CharField()


class CountryDirectionsListResponseSerializer(serializers.Serializer):
    directions_count = serializers.IntegerField()
    deals_count = serializers.IntegerField()
    total_weight_kg = serializers.FloatField()
    avg_distance_km = serializers.FloatField()
    directions = CountryDirectionSerializer(many=True)


class DirectionDetailSerializer(serializers.Serializer):
    id = serializers.CharField()
    origin_region = serializers.CharField()
    destination_region = serializers.CharField()
    shipments = serializers.IntegerField()
    weight = serializers.FloatField()
    price_value = serializers.FloatField()
    price_currency = serializers.CharField()
    pie_charts = PieChartsSerializer()
    season_chart = SeasonChartSerializer()


class CountryDirectionDetailSerializer(serializers.Serializer):
    id = serializers.CharField()
    origin_country = serializers.CharField()
    destination_country = serializers.CharField()
    shipments = serializers.IntegerField()
    weight = serializers.FloatField()
    price_value = serializers.FloatField()
    price_currency = serializers.CharField()
    pie_charts = PieChartsSerializer()
    season_chart = SeasonChartSerializer()


class BaseAnalyticsSerializer(serializers.Serializer):
    successful_deliveries = serializers.IntegerField()
    successful_deliveries_change = serializers.FloatField()
    distance_km = serializers.FloatField()
    avg_distance_km = serializers.FloatField()
    deals_count = serializers.IntegerField()
    directions_count = serializers.IntegerField()
    total_weight_kg = serializers.FloatField()
    min_price = serializers.FloatField()
    max_price = serializers.FloatField()
    price_currency = serializers.CharField()
    average_price_per_km = serializers.FloatField()
    average_price_per_km_change = serializers.FloatField()
    directions = DirectionSerializer(many=True)
    pie_charts = PieChartsSerializer()
    season_chart = SeasonChartSerializer()


class MyAnalyticsSerializer(BaseAnalyticsSerializer):
    registered_since = serializers.DateField()
    days_since_registered = serializers.IntegerField()
    rating = serializers.FloatField()


class GlobalAnalyticsSerializer(BaseAnalyticsSerializer):
    pass


class PartnerInfoSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    full_name = serializers.CharField(allow_blank=True)
    company_name = serializers.CharField(allow_blank=True)
    photo = serializers.CharField(allow_blank=True)


class PartnerAnalyticsSerializer(BaseAnalyticsSerializer):
    partner = PartnerInfoSerializer()
