from django.urls import path
from .views import (
    CountryDirectionDetailView,
    CountryDirectionsListView,
    DirectionDetailView,
    GlobalAnalyticsView,
    MyAnalyticsView,
    PartnerAnalyticsView,
    ExportAnalyticsView,
    ExportDirectionAnalyticsView,
)

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
    path(
        "directions-countries/",
        CountryDirectionsListView.as_view(),
        name="analytics-directions-countries-list",
    ),
    path(
        "directions-countries/<str:direction_id>/",
        CountryDirectionDetailView.as_view(),
        name="analytics-direction-country-detail",
    ),
    path(
        "export/",
        ExportAnalyticsView.as_view(),
        name="analytics-export",
    ),
    path(
        "export/<str:direction_id>/",
        ExportDirectionAnalyticsView.as_view(),
        name="analytics-export-direction",
    ),
]
