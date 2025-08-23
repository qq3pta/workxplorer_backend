from django.urls import path
from .views import (
    PublishCargoView,
    CargoDetailView,
    CargoRefreshView,
    MyCargosView,
    MyCargosBoardView,
)

urlpatterns = [
    path("create/", PublishCargoView.as_view()),
    path("mine/",   MyCargosView.as_view()),
    path("board/",  MyCargosBoardView.as_view()),
    path("<int:pk>/", CargoDetailView.as_view()),
    path("<int:pk>/refresh/", CargoRefreshView.as_view()),
]