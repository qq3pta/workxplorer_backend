from django.urls import path
from .views import CargoCreateView, MyCargosView

urlpatterns = [
    path("create/", CargoCreateView.as_view()),
    path("mine/",   MyCargosView.as_view()),
]