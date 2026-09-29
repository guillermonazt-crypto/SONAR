from rest_framework.permissions import BasePermission, SAFE_METHODS

def can_edit(user):
    return bool(user.is_authenticated and user.is_active and (user.is_superuser or user.rol in ('admin', 'editor')))


class EditorOnlyPermission(BasePermission):
    def has_permission(self, request, view):
        return can_edit(request.user)


class InventoryPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user.is_authenticated and user.is_active and (
            request.method in SAFE_METHODS or user.is_superuser or user.rol in ('admin', 'editor')))
