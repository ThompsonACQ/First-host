"""
Custom User model and DriverProfile for the School Shuttle Tracking System.

Roles:
  - student: Can view buses, routes, and live tracking.
  - driver:  Can log in, share GPS, view assigned bus/route.
  - admin:   Full control over the system.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Extended user model with role support."""

    ROLE_STUDENT = 'student'
    ROLE_DRIVER = 'driver'
    ROLE_ADMIN = 'admin'

    ROLE_CHOICES = [
        (ROLE_STUDENT, 'Student'),
        (ROLE_DRIVER, 'Driver'),
        (ROLE_ADMIN, 'Administrator'),
    ]

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default=ROLE_STUDENT,
    )
    phone = models.CharField(max_length=20, blank=True)
    student_id = models.CharField(max_length=50, blank=True)
    profile_picture = models.ImageField(
        upload_to='profiles/', blank=True, null=True
    )
    recovery_answers = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return f'{self.get_full_name() or self.username} ({self.role})'

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def is_student(self):
        return self.role == self.ROLE_STUDENT

    @property
    def is_driver(self):
        return self.role == self.ROLE_DRIVER

    @property
    def is_admin(self):
        return self.role == self.ROLE_ADMIN or self.is_superuser


class DriverProfile(models.Model):
    """
    Extended profile for drivers.
    Linked 1-to-1 with a User whose role is 'driver'.
    """
    STATUS_PENDING = 'PENDING'
    STATUS_APPROVED = 'APPROVED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_SUSPENDED = 'SUSPENDED'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending Approval'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_SUSPENDED, 'Suspended'),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='driver_profile',
    )
    license_number = models.CharField(max_length=50, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Driver Profile'
        verbose_name_plural = 'Driver Profiles'

    def __str__(self):
        return f'Driver: {self.user.get_full_name() or self.user.username}'

    @property
    def assigned_bus(self):
        """Returns the bus assigned to this driver, or None."""
        return getattr(self, '_assigned_bus', None) or (
            self.user.driven_buses.filter(active=True).first()
        )
