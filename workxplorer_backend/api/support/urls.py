from django.urls import path
from .views import SupportCreateView

app_name = "support"

urlpatterns = [
    path("", SupportCreateView.as_view(), name="support-create"),
]
