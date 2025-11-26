from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification
from .serializers import (
    NotificationSerializer,
    MarkReadSerializer,
    MarkAllReadSerializer,
)


class NotificationListView(generics.ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.none()
        return Notification.objects.filter(user=self.request.user).order_by("-created_at")


class NotificationMarkReadView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MarkReadSerializer

    def post(self, request, pk):
        notif = Notification.objects.filter(id=pk, user=request.user).first()

        if not notif:
            return Response({"detail": "Notification not found"}, status=404)

        notif.is_read = True
        notif.save(update_fields=["is_read"])

        return Response({"detail": "Notification marked as read"})


class NotificationMarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MarkAllReadSerializer

    def post(self, request):
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)

        return Response({"detail": "All notifications marked as read"})
