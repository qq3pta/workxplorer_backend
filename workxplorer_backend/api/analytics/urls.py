from django.urls import path
from .views import MyAnalyticsView, GlobalAnalyticsView

urlpatterns = [
    path("me/", MyAnalyticsView.as_view(), name="analytics-me"),
    path("global/", GlobalAnalyticsView.as_view(), name="analytics-global"),
]
