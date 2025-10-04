from rest_framework import serializers


class CountrySerializer(serializers.Serializer):
    code = serializers.CharField(max_length=2)
    name = serializers.CharField()


class CountrySuggestResponseSerializer(serializers.Serializer):
    results = CountrySerializer(many=True)


class CitySerializer(serializers.Serializer):
    name = serializers.CharField()
    country = serializers.CharField()
    country_code = serializers.CharField(max_length=2)


class CitySuggestResponseSerializer(serializers.Serializer):
    results = CitySerializer(many=True)
