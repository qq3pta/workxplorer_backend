from rest_framework import permissions, viewsets

from .models import UserRating
from .serializers import UserRatingSerializer


class UserRatingViewSet(viewsets.ModelViewSet):
    """CRUD API для оценок пользователей (рейтингов)."""

    queryset = UserRating.objects.select_related("rated_user", "rated_by", "order")
    serializer_class = UserRatingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        # можно фильтровать по кому или кем
        rated_user = self.request.query_params.get("rated_user")
        rated_by = self.request.query_params.get("rated_by")
        if rated_user:
            qs = qs.filter(rated_user_id=rated_user)
        if rated_by:
            qs = qs.filter(rated_by_id=rated_by)
        # показываем только оценки, в которых пользователь участвовал
        return qs.filter(order__carrier=user) | qs.filter(order__customer=user)

    def perform_create(self, serializer):
        serializer.save(rated_by=self.request.user)
