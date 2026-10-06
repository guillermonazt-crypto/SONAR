from django.urls import include, path
from rest_framework.routers import DefaultRouter
from . import views
router = DefaultRouter()
router.register('divisiones', views.DivisionViewSet)
router.register('planteles', views.PlantelViewSet)
router.register('switches', views.SwitchViewSet)
router.register('alertas', views.AlertaViewSet, basename='alerta')
router.register('mantenimientos', views.MantenimientoViewSet)
router.register('bitacora', views.BitacoraViewSet, basename='bitacora')
router.register('descubiertos', views.DescubiertoViewSet, basename='descubierto')
urlpatterns = [path('auth/session/', views.session), path('auth/login/', views.sign_in),
               path('auth/logout/', views.sign_out), path('integrations/zabbix/', views.zabbix),
               path('puertos/<int:pk>/historial/', views.port_history),
               path('switches/<int:pk>/historial/', views.switch_history),
               path('switches/<int:pk>/sintetico/', views.synthetic_history),
               path('resumen/', views.summary),
               path('vivo/', views.live),
               path('vivo/switches/<int:pk>/', views.live_switch),
               path('vivo/problemas/<int:eventid>/reconocer/', views.live_acknowledge),
               path('monitoreo/', views.monitoring),
               path('buscar/', views.search),
               path('opticas/', views.optics),
               path('opticas/prediccion/', views.optics_prediction),
               path('reportes/<slug:kind>/', views.report),
               path('respaldos/<int:pk>/', views.backup_detail),
               path('', include(router.urls))]
