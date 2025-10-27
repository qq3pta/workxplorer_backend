from django.urls import path

from .views import (
    CargoCancelView,
    CargoDetailView,
    CargoRefreshView,
    MyCargosBoardView,
    MyCargosView,
    PublicLoadsView,
    PublishCargoView,
)

app_name = "loads"

urlpatterns = [
    # --- Публичная доска ---
    path("public/", PublicLoadsView.as_view(), name="public"),
    # --- Создание груза ---
    path("create/", PublishCargoView.as_view(), name="create"),
    # --- Личный кабинет заказчика ---
    path("mine/", MyCargosView.as_view(), name="mine"),
    path("board/", MyCargosBoardView.as_view(), name="board"),
    # --- Детали / обновление / отмена по UUID ---
    path("<uuid:uuid>/", CargoDetailView.as_view(), name="detail-by-uuid"),
    path("<uuid:uuid>/refresh/", CargoRefreshView.as_view(), name="refresh-by-uuid"),
    path("<uuid:uuid>/cancel/", CargoCancelView.as_view(), name="cancel-by-uuid"),
]
