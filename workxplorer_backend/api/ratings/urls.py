from rest_framework.routers import DefaultRouter
from .views import RatingUserViewSet, UserRatingViewSet

app_name = "ratings"

router = DefaultRouter()

# CRUD рейтингов пользователей
router.register(r"ratings", UserRatingViewSet, basename="ratings")

# Каталог пользователей с рейтингами
router.register(r"rating-users", RatingUserViewSet, basename="rating-users")

urlpatterns = router.urls
