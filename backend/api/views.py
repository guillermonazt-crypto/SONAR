from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from planteles.models import Division, Plantel
from switches.models import Switch
from .permissions import InventoryPermission
from .serializers import DivisionSerializer, PlantelSerializer, SwitchSerializer, PuertoSerializer


def user_data(user):
    if not user.is_authenticated:
        return None
    return dict(id=user.pk, username=user.username, rol=user.rol,
                can_edit=user.is_superuser or user.rol in ('admin', 'editor'),
                is_staff=user.is_staff)

@require_GET
def session(request):
    return JsonResponse(dict(user=user_data(request.user), csrfToken=get_token(request)))

@require_POST
@csrf_protect
def sign_in(request):
    user = authenticate(request, username=request.POST.get('username', ''), password=request.POST.get('password', ''))
    if user is None:
        return JsonResponse({'detail': 'Usuario o contraseña incorrectos.'}, status=401)
    login(request, user)
    return JsonResponse(dict(user=user_data(user), csrfToken=get_token(request)))

@require_POST
@csrf_protect
def sign_out(request):
    logout(request)
    return JsonResponse(dict(user=None, csrfToken=get_token(request)))

class InventoryViewSet(viewsets.ModelViewSet):
    permission_classes = [InventoryPermission]
    http_method_names = ['get', 'post', 'put', 'patch', 'head', 'options']

class DivisionViewSet(InventoryViewSet):
    queryset = Division.objects.all()
    serializer_class = DivisionSerializer

class PlantelViewSet(InventoryViewSet):
    queryset = Plantel.objects.select_related('division').all()
    serializer_class = PlantelSerializer

class SwitchViewSet(InventoryViewSet):
    queryset = Switch.objects.select_related('plantel').all()
    serializer_class = SwitchSerializer

    @action(detail=True, methods=['get'])
    def puertos(self, request, pk=None):
        return Response(PuertoSerializer(self.get_object().puertos.all(), many=True).data)
