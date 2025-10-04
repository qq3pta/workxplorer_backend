from rest_framework.permissions import BasePermission

class IsOrderParticipant(BasePermission):
    def has_object_permission(self, request, view, obj):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if getattr(u, "is_staff", False) or getattr(u, "is_superuser", False):
            return True
        return (obj.customer_id == u.id) or (obj.carrier_id == u.id)