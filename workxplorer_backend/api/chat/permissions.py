from rest_framework.permissions import BasePermission

from .services import user_can_manage_group, user_is_chat_participant


class IsChatParticipant(BasePermission):
    def has_object_permission(self, request, view, obj):
        return user_is_chat_participant(obj, request.user.id)


class CanManageGroupChat(BasePermission):
    def has_object_permission(self, request, view, obj):
        return user_can_manage_group(obj, request.user.id)
