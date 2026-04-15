from django.urls import path
from .views import MyAnalyticsView, GlobalAnalyticsView, DirectionDetailView

urlpatterns = [
    path("me/", MyAnalyticsView.as_view(), name="analytics-me"),
    path("global/", GlobalAnalyticsView.as_view(), name="analytics-global"),
    path(
        "directions/<str:direction_id>/",
        DirectionDetailView.as_view(),
        name="analytics-direction-detail",
    ),
]
