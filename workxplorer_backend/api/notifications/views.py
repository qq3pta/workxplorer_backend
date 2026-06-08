from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification, NotificationPreference
from .serializers import (
    MarkAllReadSerializer,
    MarkReadSerializer,
    NotificationPreferenceSerializer,
    NotificationSerializer,
    PushDeviceSerializer,
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


class PushDeviceRegisterView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PushDeviceSerializer

    def post(self, request):
        serializer = PushDeviceSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        device = serializer.save()
        return Response(PushDeviceSerializer(device).data, status=201)


class NotificationPreferenceView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationPreferenceSerializer

    def get(self, request):
        preferences, _created = NotificationPreference.objects.get_or_create(user=request.user)
        return Response(NotificationPreferenceSerializer(preferences).data)

    def patch(self, request):
        preferences, _created = NotificationPreference.objects.get_or_create(user=request.user)
        serializer = NotificationPreferenceSerializer(
            preferences,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
