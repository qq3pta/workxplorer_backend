from django.urls import path
from .views import (
    PublishCargoView,
    CargoDetailView,
    CargoRefreshView,
    MyCargosView,
    MyCargosBoardView,
    PublicLoadsView,
    CargoCancelView,
)

urlpatterns = [
    path("public/",  PublicLoadsView.as_view(),   name="public"),
    path("create/",  PublishCargoView.as_view(),  name="create"),
    path("mine/",    MyCargosView.as_view(),      name="mine"),
    path("board/",   MyCargosBoardView.as_view(), name="board"),
    path("<int:pk>/",           CargoDetailView.as_view(),  name="detail"),
    path("<int:pk>/refresh/",   CargoRefreshView.as_view(), name="refresh"),
    path("<int:pk>/cancel/",    CargoCancelView.as_view(),  name="cancel"),
]