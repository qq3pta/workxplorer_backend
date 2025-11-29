from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Q, Sum
from rest_framework import permissions, viewsets

from .models import UserRating
from .serializers import RatingUserListSerializer, UserRatingSerializer

User = get_user_model()


class UserRatingViewSet(viewsets.ModelViewSet):
    """CRUD API для оценок пользователей."""

    queryset = UserRating.objects.select_related("rated_user", "rated_by", "order")
    serializer_class = UserRatingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        qs = super().get_queryset()

        rated_user = self.request.query_params.get("rated_user")
        rated_by = self.request.query_params.get("rated_by")

        if rated_user:
            qs = qs.filter(rated_user_id=rated_user)
        if rated_by:
            qs = qs.filter(rated_by_id=rated_by)

        return qs.filter(Q(order__customer=user) | Q(order__carrier=user))

    def perform_create(self, serializer):
        serializer.save()


class RatingUserViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Список пользователей с рейтингами (каталог).
    Вкладки:
    - Грузовладельцы
    - Логисты
    - Перевозчики
    """

    queryset = User.objects.all()
    serializer_class = RatingUserListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()

        role = self.request.query_params.get("role")
        if role in {"LOGISTIC", "CUSTOMER", "CARRIER"}:
            qs = qs.filter(role=role)

        country = self.request.query_params.get("country")
        if country:
            qs = qs.filter(country__iexact=country)

        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(
                Q(username__icontains=search)
                | Q(email__icontains=search)
                | Q(company_name__icontains=search)
            )

        qs = qs.annotate(
            avg_rating_value=Avg("ratings_received__score"),
            rating_count_value=Count("ratings_received"),
        )

        qs = qs.annotate(
            completed_orders_value=(
                Count(
                    "orders_as_carrier",
                    filter=Q(orders_as_carrier__status="delivered"),
                    distinct=True,
                )
                + Count(
                    "orders_as_customer",
                    filter=Q(orders_as_customer__status="delivered"),
                    distinct=True,
                )
            )
        )

        if role == "CARRIER":
            qs = qs.annotate(
                total_distance_value=Sum(
                    "orders_as_carrier__route_distance_km",
                    filter=Q(orders_as_carrier__status="delivered"),
                )
            )

        order_by = self.request.query_params.get("order_by")
        if order_by == "rating":
            qs = qs.order_by("-avg_rating_value")
        elif order_by == "orders":
            qs = qs.order_by("-completed_orders_value")
        elif order_by == "date":
            qs = qs.order_by("-date_joined")
        else:
            qs = qs.order_by("-rating_count_value")

        return qs
