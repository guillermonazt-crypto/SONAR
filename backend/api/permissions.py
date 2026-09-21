from rest_framework.permissions import BasePermission, SAFE_METHODS

class InventoryPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user.is_authenticated and user.is_active and (
            request.method in SAFE_METHODS or user.is_superuser or user.rol in ('admin', 'editor')))
