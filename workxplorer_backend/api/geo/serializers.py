from rest_framework import serializers


class CountrySerializer(serializers.Serializer):
    # ISO-2 code: exactly two uppercase letters
    code = serializers.RegexField(r"^[A-Z]{2}$", min_length=2, max_length=2)
    name = serializers.CharField()


class CountrySuggestResponseSerializer(serializers.Serializer):
    results = CountrySerializer(many=True)


class CitySerializer(serializers.Serializer):
    name = serializers.CharField()
    country = serializers.CharField()
    # ISO-2 code: exactly two uppercase letters
    country_code = serializers.RegexField(r"^[A-Z]{2}$", min_length=2, max_length=2)


class CitySuggestResponseSerializer(serializers.Serializer):
    results = CitySerializer(many=True)
