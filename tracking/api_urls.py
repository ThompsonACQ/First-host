"""
REST API URL patterns for the tracking app.
"""
from django.urls import path
from . import views

urlpatterns = [
    path('bus/<int:bus_id>/status/', views.bus_status_api, name='bus_status_api'),
    path('journey-plan/', views.journey_plan_api, name='journey_plan_api'),
]
