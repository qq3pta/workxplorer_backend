from django.urls import path
from .views import CargoSearchView

urlpatterns = [
    path("cargos/", CargoSearchView.as_view()),
]