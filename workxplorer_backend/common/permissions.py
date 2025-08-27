from rest_framework.permissions import BasePermission
from common.enums import Role

class IsLogistic(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == Role.LOGISTIC

class IsCustomer(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == Role.CUSTOMER

class IsCarrier(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == Role.CARRIER