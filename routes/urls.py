"""
URL patterns for the routes app.
"""
from django.urls import path
from . import views

app_name = 'routes'

urlpatterns = [
    path('routes/', views.route_list, name='route_list'),
    path('routes/create/', views.route_create, name='route_create'),
    path('routes/<int:pk>/edit/', views.route_edit, name='route_edit'),
    path('routes/<int:pk>/toggle/', views.route_toggle_active, name='route_toggle_active'),
    path('routes/<int:pk>/delete/', views.route_delete, name='route_delete'),
]
