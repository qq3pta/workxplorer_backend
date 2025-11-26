from django.urls import path

from .views import (
    NotificationListView,
    NotificationMarkReadView,
    NotificationMarkAllReadView,
)

app_name = "notifications"

urlpatterns = [
    # Список уведомлений
    path("", NotificationListView.as_view(), name="list"),
    # Отметить одно уведомление прочитанным
    path("<int:pk>/mark-read/", NotificationMarkReadView.as_view(), name="mark-read"),
    # Отметить все прочитанными
    path("mark-all-read/", NotificationMarkAllReadView.as_view(), name="mark-all-read"),
]
