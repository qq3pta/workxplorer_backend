from rest_framework.routers import DefaultRouter

from .views import RatingUserViewSet, UserRatingViewSet

app_name = "ratings"

router = DefaultRouter()

router.register(r"", UserRatingViewSet, basename="ratings")

router.register(r"users", RatingUserViewSet, basename="rating-users")

urlpatterns = router.urls
