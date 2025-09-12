from rest_framework.routers import DefaultRouter

from .views import OfferViewSet

app_name = "offers"

router = DefaultRouter()
router.register(r"", OfferViewSet, basename="offers")

urlpatterns = router.urls