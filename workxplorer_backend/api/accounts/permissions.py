from rest_framework.permissions import BasePermission

class IsCustomer(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "CUSTOMER"

class IsCarrier(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "CARRIER"

class IsLogistic(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "LOGISTIC"