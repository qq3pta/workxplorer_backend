from django.urls import path

from .views import CitySuggestView, CountrySuggestView, RegionSuggestView

urlpatterns = [
    path("suggest/countries/", CountrySuggestView.as_view(), name="geo-suggest-countries"),
    path("suggest/cities/", CitySuggestView.as_view(), name="geo-suggest-cities"),
    path("suggest/regions/", RegionSuggestView.as_view(), name="geo-suggest-regions"),
]
