"""
URL patterns for the buses app.
"""
from django.urls import path
from . import views

app_name = 'buses'

urlpatterns = [
    path('buses/', views.bus_list, name='bus_list'),
    path('buses/create/', views.bus_create, name='bus_create'),
    path('buses/<int:pk>/edit/', views.bus_edit, name='bus_edit'),
    path('buses/<int:pk>/toggle/', views.bus_toggle_active, name='bus_toggle_active'),
    path('buses/<int:pk>/delete/', views.bus_delete, name='bus_delete'),
]
