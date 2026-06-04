from django.urls import path

from .views import (
    NotificationListView,
    NotificationMarkAllReadView,
    NotificationMarkReadView,
    NotificationPreferenceView,
    PushDeviceRegisterView,
)

app_name = "notifications"

urlpatterns = [
    path("", NotificationListView.as_view(), name="list"),
    path("push-tokens/", PushDeviceRegisterView.as_view(), name="push-token-register"),
    path("preferences/", NotificationPreferenceView.as_view(), name="preferences"),
    path("<int:pk>/mark-read/", NotificationMarkReadView.as_view(), name="mark-read"),
    path("mark-all-read/", NotificationMarkAllReadView.as_view(), name="mark-all-read"),
]
