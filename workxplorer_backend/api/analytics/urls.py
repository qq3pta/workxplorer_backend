from django.urls import path
from .views import MyAnalyticsView, GlobalAnalyticsView, DirectionDetailView, PartnerAnalyticsView

urlpatterns = [
    path("me/", MyAnalyticsView.as_view(), name="analytics-me"),
    path("global/", GlobalAnalyticsView.as_view(), name="analytics-global"),
    path(
        "partners/<int:partner_id>/",
        PartnerAnalyticsView.as_view(),
        name="analytics-partner-detail",
    ),
    path(
        "directions/<str:direction_id>/",
        DirectionDetailView.as_view(),
        name="analytics-direction-detail",
    ),
]
