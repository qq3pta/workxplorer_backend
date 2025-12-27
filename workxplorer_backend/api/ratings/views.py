from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Q, Sum
from rest_framework import permissions, viewsets
from django.db.models.functions import Coalesce
from django.db.models import IntegerField, ExpressionWrapper

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

        return qs.filter(Q(order__customer=user) | Q(order__carrier=user) | Q(order__logistic=user))

    def perform_create(self, serializer):
        serializer.save()


User = get_user_model()


class RatingUserViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.all()
    serializer_class = RatingUserListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()

        role = self.request.query_params.get("role")
        if role:
            role = role.upper()

        if role in {"LOGISTIC", "CUSTOMER", "CARRIER"}:
            qs = qs.filter(role=role)

        user_id = self.request.query_params.get("id")
        if user_id:
            qs = qs.filter(id=user_id)

        country = self.request.query_params.get("country")
        if country:
            qs = qs.filter(profile__country__iexact=country)

        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(
                Q(username__icontains=search)
                | Q(email__icontains=search)
                | Q(company_name__icontains=search)
            )

        qs = qs.annotate(
            avg_rating_value=Coalesce(Avg("ratings_received__score"), 0.0),
            rating_count_value=Count("ratings_received", distinct=True),
            orders_total_value=ExpressionWrapper(
                Count("orders_as_carrier", distinct=True)
                + Count("orders_as_customer", distinct=True),
                output_field=IntegerField(),
            ),
            orders_completed_value=ExpressionWrapper(
                Count(
                    "orders_as_carrier",
                    filter=Q(orders_as_carrier__status="delivered"),
                    distinct=True,
                )
                + Count(
                    "orders_as_customer",
                    filter=Q(orders_as_customer__status="delivered"),
                    distinct=True,
                ),
                output_field=IntegerField(),
            ),
            orders_in_progress_value=ExpressionWrapper(
                Count(
                    "orders_as_carrier",
                    filter=Q(orders_as_carrier__status="in_process"),
                    distinct=True,
                )
                + Count(
                    "orders_as_customer",
                    filter=Q(orders_as_customer__status="in_process"),
                    distinct=True,
                ),
                output_field=IntegerField(),
            ),
            orders_queued_value=ExpressionWrapper(
                Count(
                    "orders_as_carrier",
                    filter=Q(orders_as_carrier__status="pending"),
                    distinct=True,
                )
                + Count(
                    "orders_as_customer",
                    filter=Q(orders_as_customer__status="pending"),
                    distinct=True,
                ),
                output_field=IntegerField(),
            ),
            orders_excellent_value=Count(
                "ratings_received",
                filter=Q(ratings_received__score=5),
                distinct=True,
            ),
        )

        if role == "CARRIER":
            qs = qs.annotate(
                total_distance_value=Sum(
                    "orders_as_carrier__route_distance_km",
                    filter=Q(orders_as_carrier__status="delivered"),
                )
            )

        min_rating = self.request.query_params.get("min_rating") or self.request.query_params.get(
            "rating_min"
        )
        max_rating = self.request.query_params.get("max_rating") or self.request.query_params.get(
            "rating_max"
        )

        if min_rating:
            try:
                qs = qs.filter(avg_rating_value__gte=float(min_rating))
            except ValueError:
                pass

        if max_rating:
            try:
                qs = qs.filter(avg_rating_value__lte=float(max_rating))
            except ValueError:
                pass

        return qs
