from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification
from .serializers import NotificationSerializer


class NotificationListView(generics.ListAPIView):
    """
    Возвращает список уведомлений текущего пользователя.
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user).order_by("-created_at")


class NotificationMarkReadView(APIView):
    """
    Помечает одно уведомление как прочитанное.
    POST /notifications/<id>/mark-read/
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        notif = Notification.objects.filter(id=pk, user=request.user).first()

        if not notif:
            return Response({"detail": "Notification not found"}, status=404)

        notif.is_read = True
        notif.save(update_fields=["is_read"])

        return Response({"detail": "Notification marked as read"})


class NotificationMarkAllReadView(APIView):
    """
    Помечает все непрочитанные уведомления как прочитанные.
    POST /notifications/mark-all-read/
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)

        return Response({"detail": "All notifications marked as read"})
