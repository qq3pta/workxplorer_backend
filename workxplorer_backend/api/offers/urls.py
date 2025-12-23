from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import OfferViewSet, OfferStatusLogListView

app_name = "offers"

router = DefaultRouter()
router.register(r"", OfferViewSet, basename="offers")

urlpatterns = [
    *router.urls,
    path(
        "<int:pk>/logs/",
        OfferStatusLogListView.as_view(),
        name="offer-logs",
    ),
]
