from django.urls import include, path
from rest_framework.routers import DefaultRouter
from . import views
router = DefaultRouter()
router.register('divisiones', views.DivisionViewSet)
router.register('planteles', views.PlantelViewSet)
router.register('switches', views.SwitchViewSet)
urlpatterns = [path('auth/session/', views.session), path('auth/login/', views.sign_in),
               path('auth/logout/', views.sign_out), path('integrations/zabbix/', views.zabbix),
               path('puertos/<int:pk>/historial/', views.port_history),
               path('switches/<int:pk>/historial/', views.switch_history),
               path('', include(router.urls))]
