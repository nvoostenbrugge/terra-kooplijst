from django.urls import path

from . import views

urlpatterns = [
    path('', views.pagina),
    path('health/', views.health),
    path('api/staat/', views.staat),
    path('api/regels/', views.regel_nieuw),
    path('api/regels/<int:pk>/', views.regel_wijzig),
    path('api/regels/<int:pk>/akkoord/', views.regel_akkoord),
    path('api/regels/<int:pk>/afwijzen/', views.regel_afwijzen),
    path('api/akkoord/', views.akkoord_alles),
    path('api/besteld/', views.besteld),
    path('api/bestellingen/<int:pk>/volglink/', views.bestelling_volglink),
    path('api/ontvangen/', views.ontvangen),
    path('api/wagens/', views.wagen_melden),
    path('api/vultaak/', views.vultaak),
    path('api/instellingen/', views.instellingen),
    path('api/team/', views.team),
    path('api/koppel/', views.koppel_naam),
    path('api/import/', views.importeer),
]
