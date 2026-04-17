from django.urls import path

from .views import ConsultationRequestView, SupportCreateView

app_name = "support"

urlpatterns = [
    path("", SupportCreateView.as_view(), name="support-create"),
    path("consultation/", ConsultationRequestView.as_view()),
]
