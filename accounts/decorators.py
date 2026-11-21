"""
Authentication decorators for role-based access control.
"""
from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


def admin_required(view_func):
    """Restrict view to admin users only."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        if not (request.user.is_admin or request.user.is_superuser):
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('school_settings:home')
        return view_func(request, *args, **kwargs)
    return wrapper


def driver_required(view_func):
    """Restrict view to driver users only."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        if not (request.user.is_driver or request.user.is_admin or request.user.is_superuser):
            messages.error(request, 'This page is for drivers only.')
            return redirect('home')
        return view_func(request, *args, **kwargs)
    return wrapper


def login_required_custom(view_func):
    """Require login, redirect to custom login page."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        return view_func(request, *args, **kwargs)
    return wrapper
