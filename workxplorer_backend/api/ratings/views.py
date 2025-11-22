from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import permissions, viewsets

from .models import UserRating
from .serializers import RatingUserListSerializer, UserRatingSerializer

User = get_user_model()


class UserRatingViewSet(viewsets.ModelViewSet):
    """CRUD API для оценок пользователей (рейтингов)."""

    queryset = UserRating.objects.select_related("rated_user", "rated_by", "order")
    serializer_class = UserRatingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user

        # фильтрация по кому / кем
        rated_user = self.request.query_params.get("rated_user")
        rated_by = self.request.query_params.get("rated_by")
        if rated_user:
            qs = qs.filter(rated_user_id=rated_user)
        if rated_by:
            qs = qs.filter(rated_by_id=rated_by)

        # показываем только оценки, в которых текущий пользователь участвовал
        qs = qs.filter(Q(order__carrier=user) | Q(order__customer=user))
        return qs

    def perform_create(self, serializer):
        serializer.save(rated_by=self.request.user)


class RatingUserViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Список пользователей с рейтингами
    (экран с вкладками 'Грузовладельцы / Логисты / Перевозчики').
    """

    queryset = User.objects.all()
    serializer_class = RatingUserListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()

        # фильтр по роли для вкладок
        role = self.request.query_params.get("role")
        if role in {"LOGISTIC", "CUSTOMER", "CARRIER"}:
            qs = qs.filter(role=role)

        # сюда позже можно добавить сортировки (order=avg_rating / completed_orders / …)
        return qs
