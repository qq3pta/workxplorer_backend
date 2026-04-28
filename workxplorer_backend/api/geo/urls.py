from django.urls import path

from .views import (
    CitySuggestView,
    CountrySuggestView,
    RegionSuggestView,
    MapCountriesView,
    MapRegionsView,
    MapCitiesView,
)

urlpatterns = [
    path("suggest/countries/", CountrySuggestView.as_view(), name="geo-suggest-countries"),
    path("suggest/cities/", CitySuggestView.as_view(), name="geo-suggest-cities"),
    path("suggest/regions/", RegionSuggestView.as_view(), name="geo-suggest-regions"),
    path("map/countries/", MapCountriesView.as_view(), name="map-countries"),
    path("map/regions/", MapRegionsView.as_view(), name="map-regions"),
    path("map/cities/", MapCitiesView.as_view(), name="map-cities"),
]
