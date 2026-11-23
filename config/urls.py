"""
Main URL configuration for School Shuttle Bus Tracking System.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from tracking import views as tracking_views

urlpatterns = [
    # Django default admin (for superuser use)
    path('django-admin/', admin.site.urls),

    # Public pages
    path('', include('school_settings.urls')),       # Home page + school settings
    path('accounts/', include('accounts.urls')),     # Login, logout, driver dashboard, user mgmt
    path('tracking/', include('tracking.urls')),     # Live tracking pages (public)

    # Admin dashboard sub-pages
    path('admin-dashboard/dashboard/', tracking_views.admin_dashboard, name='admin_dashboard'),
    path('admin-dashboard/emergencies/<int:alert_id>/acknowledge/', tracking_views.acknowledge_emergency, name='acknowledge_emergency'),
    path('admin-dashboard/emergencies/<int:alert_id>/message/', tracking_views.admin_emergency_message, name='admin_emergency_message'),
    path('admin-dashboard/trips/', tracking_views.trip_history, name='trip_history'),
    path('admin-dashboard/trips/<int:trip_id>/', tracking_views.trip_replay, name='trip_replay'),
    path('admin-dashboard/', include(('buses.urls', 'buses'), namespace='buses')),
    path('admin-dashboard/', include(('routes.urls', 'routes'), namespace='routes')),

    # REST API endpoints
    path('api/tracking/', include('tracking.api_urls')),
]

# Serve local media uploads on both development and Render fallback instances.
# Cloudinary returns an external URL and does not use this route.
default_storage = settings.STORAGES['default']['BACKEND']
if default_storage == 'django.core.files.storage.FileSystemStorage':
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Serve static files only in development; production uses WhiteNoise.
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
