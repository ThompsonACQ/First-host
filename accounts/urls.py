"""
URL patterns for the accounts app.
"""
from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('auth/', views.auth_landing, name='auth_landing'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('admin-security/', views.admin_security, name='admin_security'),
    path('admin-change-password/', views.admin_change_password, name='admin_change_password'),
    path('admin-recovery/', views.admin_recovery, name='admin_recovery'),
    
    # Registration
    path('signup/student/', views.student_signup, name='student_signup'),
    path('signup/driver/', views.driver_signup, name='driver_signup'),
    
    # Dashboard
    path('driver/', views.driver_dashboard, name='driver_dashboard'),
    path('driver/occupancy/', views.update_bus_occupancy, name='update_bus_occupancy'),
    path('driver/stop-sharing/', views.stop_driver_sharing, name='stop_driver_sharing'),
    path('driver/emergency/', views.driver_emergency, name='driver_emergency'),
    path('driver/emergency-response/', views.latest_emergency_response, name='latest_emergency_response'),
    path('driver/emergencies/<int:alert_id>/message/', views.driver_emergency_message, name='driver_emergency_message'),
    
    # Admin User Management
    path('users/', views.user_list, name='user_list'),
    path('users/create/', views.user_create, name='user_create'),
    path('users/<int:pk>/edit/', views.user_edit, name='user_edit'),
    path('users/<int:pk>/toggle/', views.user_toggle_active, name='user_toggle_active'),
    path('users/<int:pk>/approve/', views.driver_approve, name='driver_approve'),
    path('users/<int:pk>/reject/', views.driver_reject, name='driver_reject'),
    path('users/<int:pk>/suspend/', views.driver_suspend, name='driver_suspend'),
]
