from django.urls import path

from .views import ChatPingView

urlpatterns = [
    path("ping/", ChatPingView.as_view(), name="chat-ping"),
]
