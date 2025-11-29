from django.urls import path
from .views import (
    CargoCancelView,
    CargoDetailView,
    CargoRefreshView,
    MyCargosBoardView,
    MyCargosView,
    PublicLoadsView,
    PublishCargoView,
    CargoVisibilityView,
    CargoInviteGenerateView,
    CargoInviteOpenView,
)

app_name = "loads"

urlpatterns = [
    path("public/", PublicLoadsView.as_view(), name="public"),
    path("create/", PublishCargoView.as_view(), name="create"),
    path("mine/", MyCargosView.as_view(), name="mine"),
    path("board/", MyCargosBoardView.as_view(), name="board"),
    path("<uuid:uuid>/", CargoDetailView.as_view(), name="detail-by-uuid"),
    path("<uuid:uuid>/refresh/", CargoRefreshView.as_view(), name="refresh-by-uuid"),
    path("<uuid:uuid>/cancel/", CargoCancelView.as_view(), name="cancel-by-uuid"),
    path("<uuid:uuid>/visibility/", CargoVisibilityView.as_view()),
    path("<uuid:uuid>/invite/generate/", CargoInviteGenerateView.as_view(), name="invite-generate"),
    path("invite/<str:token>/", CargoInviteOpenView.as_view(), name="invite-open"),
]
