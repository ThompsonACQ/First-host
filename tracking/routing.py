"""
WebSocket URL routing for the tracking app.
"""

from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/tracking/(?P<bus_id>\d+)/$', consumers.BusTrackingConsumer.as_asgi()),
    re_path(r'ws/admin-alerts/$', consumers.AdminAlertConsumer.as_asgi()),
]
