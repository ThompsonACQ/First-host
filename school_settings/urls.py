"""
URL patterns for school_settings app.
"""
from django.urls import path
from . import views

app_name = 'school_settings'

urlpatterns = [
    path('', views.home, name='home'),
    path('settings/', views.settings_view, name='settings'),
    path('settings/reset-colors/', views.reset_colors, name='reset_colors'),
    path('api/preview/', views.preview_api, name='preview_api'),
]
