from django.urls import path
from .views import CountrySuggestView, CitySuggestView

urlpatterns = [
    path("suggest/countries/", CountrySuggestView.as_view(), name="geo-suggest-countries"),
    path("suggest/cities/", CitySuggestView.as_view(), name="geo-suggest-cities"),
]