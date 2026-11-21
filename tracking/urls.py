"""
HTTP URL patterns for the tracking app.
"""
from django.urls import path
from . import views

app_name = 'tracking'

urlpatterns = [
    path('', views.bus_list, name='bus_list'),
    path('plan/', views.journey_planner, name='journey_planner'),
    path('<int:bus_id>/', views.live_tracking, name='live_tracking'),
]
