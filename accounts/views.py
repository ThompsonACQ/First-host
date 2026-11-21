"""
Accounts views — login, logout, registration, and role-based redirects.
"""

from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.hashers import check_password
from django.contrib import messages
from django.core.cache import cache
from django.db.models import Q
import json
import hashlib
import logging

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.db import transaction

from .models import User, DriverProfile
from .decorators import admin_required
from .forms import (
    AdminRecoveryForm,
    AdminSecuritySetupForm,
    StudentRegistrationForm,
    DriverRegistrationForm,
    normalize_recovery_answer,
)

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------
# Authentication & Registration views
# -----------------------------------------------------------------------

def auth_landing(request):
    """Landing page to choose registration/login type."""
    if request.user.is_authenticated:
        return _redirect_by_role(request.user)
    return render(request, 'accounts/auth_landing.html')


def student_signup(request):
    if request.user.is_authenticated:
        return _redirect_by_role(request.user)

    if request.method == 'POST':
        form = StudentRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, 'Your student account has been created successfully. Please sign in.')
            return redirect('accounts:login')
    else:
        form = StudentRegistrationForm()
        
    return render(request, 'accounts/signup.html', {
        'form': form,
        'title': 'Sign Up as Student',
        'role': 'student'
    })


def driver_signup(request):
    if request.user.is_authenticated:
        return _redirect_by_role(request.user)

    if request.method == 'POST':
        form = DriverRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, 'Your driver account has been created successfully. Please sign in.')
            return redirect('accounts:login')
    else:
        form = DriverRegistrationForm()
        
    return render(request, 'accounts/signup.html', {
        'form': form,
        'title': 'Sign Up as Driver',
        'role': 'driver'
    })


def login_view(request):
    """Custom login view with role-based redirect."""
    if request.user.is_authenticated:
        return _redirect_by_role(request.user)

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            
            # Check driver status before allowing full login
            if user.is_driver and hasattr(user, 'driver_profile'):
                status = user.driver_profile.status
                if status == DriverProfile.STATUS_REJECTED:
                    messages.error(request, 'Your driver account has not been approved by the administrator.')
                    return redirect('accounts:login')
                elif status == DriverProfile.STATUS_SUSPENDED:
                    messages.error(request, 'Your driver account has been suspended. Please contact the administrator.')
                    return redirect('accounts:login')
            
            login(request, user)
            return _redirect_by_role(user)
        else:
            messages.error(request, 'Invalid username or password.')
    else:
        form = AuthenticationForm()

    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    """Logout and redirect to home."""
    logout(request)
    messages.success(request, 'You have been logged out.')
    return redirect('school_settings:home')


@login_required
@admin_required
@require_http_methods(['GET', 'POST'])
def admin_security(request):
    """Let an authenticated administrator update credentials and recovery answers."""
    if request.method == 'POST':
        form = AdminSecuritySetupForm(request.POST, user=request.user)
        if form.is_valid():
            request.user.email = form.cleaned_data['email']
            request.user.username = form.cleaned_data['email']
            request.user.set_password(form.cleaned_data['new_password'])
            request.user.recovery_answers = form.recovery_answers()
            request.user.save(update_fields=[
                'email', 'username', 'password', 'recovery_answers',
            ])
            update_session_auth_hash(request, request.user)
            messages.success(request, 'Your administrator login and recovery questions have been updated.')
            return redirect('accounts:admin_security')
    else:
        form = AdminSecuritySetupForm(user=request.user)
    return render(request, 'accounts/admin_security.html', {'form': form})


@login_required
@admin_required
@require_http_methods(['GET', 'POST'])
def admin_change_password(request):
    """Let an administrator change the password for their own account."""
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, request.user)
            messages.success(request, 'Your administrator password has been changed.')
            return redirect('accounts:admin_change_password')
    else:
        form = PasswordChangeForm(request.user)
    for field in form.fields.values():
        field.widget.attrs.update({
            'class': 'form-input',
            'autocomplete': 'off',
        })
    form.fields['old_password'].widget.attrs['autocomplete'] = 'current-password'
    form.fields['new_password1'].widget.attrs['autocomplete'] = 'new-password'
    form.fields['new_password2'].widget.attrs['autocomplete'] = 'new-password'
    return render(request, 'accounts/admin_change_password.html', {'form': form})


def _recovery_rate_limit_key(request):
    address = request.META.get('REMOTE_ADDR', 'unknown')
    digest = hashlib.sha256(address.encode('utf-8')).hexdigest()
    return f'admin-recovery:{digest}'


def _recovery_attempt_count(request):
    key = _recovery_rate_limit_key(request)
    if cache.add(key, 1, timeout=900):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        cache.add(key, 1, timeout=900)
        return 1


def _match_admin_recovery_answers(form):
    submitted = {
        form.cleaned_data[f'question_{index}']: normalize_recovery_answer(
            form.cleaned_data[f'answer_{index}']
        )
        for index in range(1, 4)
    }
    admins = User.objects.filter(is_active=True).filter(
        Q(role=User.ROLE_ADMIN) | Q(is_superuser=True)
    ).only('id', 'recovery_answers')
    for user in admins:
        saved = user.recovery_answers or {}
        if set(saved) != set(submitted):
            continue
        answers_match = True
        for question, answer in submitted.items():
            if not check_password(answer, saved.get(question, '')):
                answers_match = False
        if answers_match:
            return user
    return None


@require_http_methods(['GET', 'POST'])
def admin_recovery(request):
    """Recover an administrator login using all three saved recovery answers."""
    if request.method == 'POST':
        if _recovery_attempt_count(request) > 5:
            form = AdminRecoveryForm(request.POST)
            form.add_error(None, 'Too many recovery attempts. Please try again in 15 minutes.')
            return render(request, 'accounts/admin_recovery.html', {'form': form}, status=429)

        form = AdminRecoveryForm(request.POST)
        if form.is_valid():
            user = _match_admin_recovery_answers(form)
            if user:
                new_email = form.cleaned_data['email']
                email_in_use = User.objects.filter(
                    Q(email__iexact=new_email) | Q(username__iexact=new_email)
                ).exclude(pk=user.pk).exists()
                if not email_in_use:
                    with transaction.atomic():
                        user = User.objects.select_for_update().get(pk=user.pk)
                        user.email = new_email
                        user.username = new_email
                        user.set_password(form.cleaned_data['new_password'])
                        user.save(update_fields=['email', 'username', 'password'])
                    cache.delete(_recovery_rate_limit_key(request))
                    logger.warning(
                        'Administrator account recovered for user_id=%s from IP=%s',
                        user.pk, request.META.get('REMOTE_ADDR', 'unknown'),
                    )
                    messages.success(request, 'Your administrator login was reset. Sign in with your new email and password.')
                    return redirect('accounts:login')
            form.add_error(None, 'The recovery answers could not be verified. No account was changed.')
    else:
        form = AdminRecoveryForm()
    return render(request, 'accounts/admin_recovery.html', {'form': form})


def _redirect_by_role(user):
    """Return an HttpResponseRedirect to the appropriate dashboard."""
    if user.is_admin or user.is_superuser:
        return redirect('admin_dashboard')
    elif user.is_driver:
        return redirect('accounts:driver_dashboard')
    else:
        return redirect('tracking:bus_list')


# -----------------------------------------------------------------------
# Driver dashboard
# -----------------------------------------------------------------------

def driver_dashboard(request):
    """Driver dashboard — GPS sharing controls."""
    if not request.user.is_authenticated:
        return redirect('accounts:login')
    if not (request.user.is_driver or request.user.is_superuser):
        messages.error(request, 'This page is for drivers only.')
        return redirect('school_settings:home')

    driver_profile = getattr(request.user, 'driver_profile', None)
    
    # Get the bus assigned to this driver
    bus = (
        request.user.driven_buses
        .filter(active=True)
        .select_related('route')
        .first()
    )

    return render(request, 'accounts/driver_dashboard.html', {
        'driver': request.user,
        'bus': bus,
        'driver_profile': driver_profile,
    })


@require_POST
@login_required
def update_bus_occupancy(request):
    """Allow an approved assigned driver to record the current passenger count."""
    try:
        occupied_seats = int(json.loads(request.body).get('occupied_seats'))
    except (TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({'detail': 'Enter a whole number of occupied seats.'}, status=400)

    with transaction.atomic():
        bus = request.user.driven_buses.select_for_update().filter(active=True).first()
        profile = getattr(request.user, 'driver_profile', None)
        if not bus or not profile or profile.status != DriverProfile.STATUS_APPROVED:
            return JsonResponse({'detail': 'You are not authorized to update bus occupancy.'}, status=403)
        if not 0 <= occupied_seats <= bus.capacity:
            return JsonResponse({'detail': f'Occupancy must be between 0 and {bus.capacity}.'}, status=400)

        previous_occupied = bus.occupied_seats
        if occupied_seats != previous_occupied:
            from buses.models import OccupancyLog
            OccupancyLog.objects.create(
                bus=bus,
                driver=request.user,
                previous_occupied=previous_occupied,
                occupied_seats=occupied_seats,
            )
            bus.occupied_seats = occupied_seats
            bus.save(update_fields=['occupied_seats', 'updated_at'])

    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
    async_to_sync(get_channel_layer().group_send)(
        f'bus_{bus.pk}',
        {'type': 'broadcast_occupancy', 'occupied_seats': occupied_seats,
         'capacity': bus.capacity, 'available_seats': bus.capacity - occupied_seats},
    )

    return JsonResponse({
        'occupied_seats': occupied_seats,
        'capacity': bus.capacity,
        'available_seats': bus.capacity - occupied_seats,
    })


@require_POST
@login_required
def stop_driver_sharing(request):
    """End a browser sharing session without deleting the last saved GPS point."""
    bus = request.user.driven_buses.filter(active=True).first()
    if not bus:
        return JsonResponse({'detail': 'No active bus is assigned to this driver.'}, status=404)

    bus.status = 'stopped'
    bus.save(update_fields=['status', 'updated_at'])

    from tracking.safety import finish_active_trip
    finish_active_trip(bus, request.user)

    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
    async_to_sync(get_channel_layer().group_send)(
        f'bus_{bus.pk}', {'type': 'broadcast_status', 'status': 'stopped'},
    )
    return JsonResponse({'status': 'stopped', 'last_location_saved': bus.latest_location is not None})


@require_POST
@login_required
def driver_emergency(request):
    """Record a driver SOS and push it to every connected administrator."""
    bus = request.user.driven_buses.select_related('route').filter(active=True).first()
    profile = getattr(request.user, 'driver_profile', None)
    if not bus or not profile or profile.status != DriverProfile.STATUS_APPROVED:
        return JsonResponse({'detail': 'You are not authorized to raise an emergency alert.'}, status=403)

    try:
        emergency_type = json.loads(request.body or '{}').get('emergency_type')
    except json.JSONDecodeError:
        emergency_type = None
    from tracking.models import EmergencyAlert, Trip
    valid_types = {choice[0] for choice in EmergencyAlert.TYPE_CHOICES}
    if emergency_type not in valid_types:
        return JsonResponse({'detail': 'Select a valid emergency type.'}, status=400)
    location = bus.latest_location
    trip = Trip.objects.filter(bus=bus, driver=request.user, ended_at__isnull=True).first()
    alert = EmergencyAlert.objects.create(
        bus=bus, driver=request.user, trip=trip, route_name=bus.route_name, emergency_type=emergency_type,
        latitude=location.latitude if location else None,
        longitude=location.longitude if location else None,
    )
    payload = {
        'type': 'emergency_alert', 'alert_id': alert.pk, 'bus_id': bus.pk,
        'bus_number': bus.bus_number, 'driver_name': bus.driver_name,
        'route_name': bus.route_name, 'latitude': alert.latitude,
        'longitude': alert.longitude, 'created_at': alert.created_at.isoformat(),
        'status': alert.status, 'emergency_type': alert.get_emergency_type_display(),
    }
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
    async_to_sync(get_channel_layer().group_send)('admin_alerts', payload)
    return JsonResponse(payload, status=201)


@require_GET
@login_required
def latest_emergency_response(request):
    """Fallback for a driver who reconnects after an admin responds to SOS."""
    if not request.user.is_driver:
        return JsonResponse({'detail': 'Driver access required.'}, status=403)
    from tracking.models import EmergencyAlert
    alert = (EmergencyAlert.objects.filter(driver=request.user, responded_at__isnull=False)
             .select_related('acknowledged_by').order_by('-responded_at').first())
    if not alert:
        return JsonResponse({'response': None})
    return JsonResponse({'response': {
        'alert_id': alert.pk,
        'message': alert.admin_message,
        'admin_name': alert.acknowledged_by.get_full_name() or alert.acknowledged_by.username if alert.acknowledged_by else 'An administrator',
        'responded_at': alert.responded_at.isoformat(),
    }})


@require_POST
@login_required
def driver_emergency_message(request, alert_id):
    """Let the driver reply privately to administrators about their SOS."""
    from tracking.models import EmergencyAlert, EmergencyMessage
    alert = get_object_or_404(EmergencyAlert, pk=alert_id, driver=request.user)
    body = request.POST.get('message', '').strip()
    if not body:
        return JsonResponse({'detail': 'Enter a message.'}, status=400)
    item = EmergencyMessage.objects.create(alert=alert, sender=request.user, body=body)
    payload = {'type': 'emergency_message', 'alert_id': alert.pk, 'sender_name': request.user.get_full_name() or request.user.username,
               'sender_role': 'driver', 'body': item.body, 'created_at': item.created_at.isoformat()}
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
    async_to_sync(get_channel_layer().group_send)('admin_alerts', payload)
    return JsonResponse(payload, status=201)



# -----------------------------------------------------------------------
# Admin user management
# -----------------------------------------------------------------------

class UserCreateForm(forms.ModelForm):
    """Form for admin to create users with a role."""
    password = forms.CharField(widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'role', 'phone', 'password']

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
            # Create driver profile if role is driver
            if user.role == User.ROLE_DRIVER:
                DriverProfile.objects.get_or_create(user=user)
        return user


class UserEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'role', 'phone', 'is_active']


@admin_required
def user_list(request):
    """List all users."""
    users = User.objects.all().order_by('role', 'username')
    return render(request, 'accounts/user_list.html', {'users': users})


@admin_required
def user_create(request):
    """Create a new user."""
    if request.method == 'POST':
        form = UserCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f'User {user.username} created successfully.')
            return redirect('accounts:user_list')
    else:
        form = UserCreateForm()
    return render(request, 'accounts/user_form.html', {'form': form, 'title': 'Add User'})


@admin_required
def user_edit(request, pk):
    """Edit an existing user."""
    user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        form = UserEditForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            # Ensure driver profile exists if role changed to driver
            if user.role == User.ROLE_DRIVER:
                DriverProfile.objects.get_or_create(user=user)
            messages.success(request, f'User {user.username} updated.')
            return redirect('accounts:user_list')
    else:
        form = UserEditForm(instance=user)
    return render(request, 'accounts/user_form.html', {
        'form': form,
        'title': f'Edit User: {user.username}',
        'edit_user': user,
    })


@admin_required
def user_toggle_active(request, pk):
    """Toggle a user's active status."""
    user = get_object_or_404(User, pk=pk)
    user.is_active = not user.is_active
    user.save(update_fields=['is_active'])
    status = 'activated' if user.is_active else 'deactivated'
    messages.success(request, f'User {user.username} has been {status}.')
    return redirect('accounts:user_list')


@admin_required
def driver_approve(request, pk):
    user = get_object_or_404(User, pk=pk, role=User.ROLE_DRIVER)
    if hasattr(user, 'driver_profile'):
        user.driver_profile.status = DriverProfile.STATUS_APPROVED
        user.driver_profile.save()
        messages.success(request, f'Driver {user.get_full_name()} approved.')
    return redirect('accounts:user_list')


@admin_required
def driver_reject(request, pk):
    user = get_object_or_404(User, pk=pk, role=User.ROLE_DRIVER)
    if hasattr(user, 'driver_profile'):
        user.driver_profile.status = DriverProfile.STATUS_REJECTED
        user.driver_profile.save()
        messages.warning(request, f'Driver {user.get_full_name()} rejected.')
    return redirect('accounts:user_list')


@admin_required
def driver_suspend(request, pk):
    user = get_object_or_404(User, pk=pk, role=User.ROLE_DRIVER)
    if hasattr(user, 'driver_profile'):
        user.driver_profile.status = DriverProfile.STATUS_SUSPENDED
        user.driver_profile.save()
        messages.error(request, f'Driver {user.get_full_name()} suspended.')
    return redirect('accounts:user_list')
