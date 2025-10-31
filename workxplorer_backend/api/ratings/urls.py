from rest_framework.routers import DefaultRouter

from .views import UserRatingViewSet

app_name = "ratings"

router = DefaultRouter()
router.register(r"", UserRatingViewSet, basename="ratings")

urlpatterns = router.urls
