"""
SchoolSettings model — singleton that stores all school identity and branding.

Defaults are applied when no record exists so the site never breaks without
an admin having configured it yet.
"""

from django.db import models


DEFAULT_PRIMARY_COLOR = '#2E3192'
DEFAULT_SECONDARY_COLOR = '#0F172A'
DEFAULT_ACCENT_COLOR = '#FFF102'
DEFAULT_BRAND_PALETTE = (
    DEFAULT_PRIMARY_COLOR,
    DEFAULT_SECONDARY_COLOR,
    DEFAULT_ACCENT_COLOR,
)


class SchoolSettings(models.Model):
    """
    Singleton model. Only one active record should exist.
    Use SchoolSettings.get_settings() to safely retrieve it.
    """

    # ----------------------------------------------------------------
    # School Information
    # ----------------------------------------------------------------
    school_name = models.CharField(
        max_length=255, default='School Shuttle Tracker'
    )
    motto = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    about = models.TextField(blank=True)
    address = models.CharField(max_length=500, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)

    # ----------------------------------------------------------------
    # Branding
    # ----------------------------------------------------------------
    logo = models.ImageField(upload_to='school/logo/', blank=True, null=True)
    favicon = models.ImageField(
        upload_to='school/favicon/', blank=True, null=True
    )
    primary_color = models.CharField(
        max_length=7, default=DEFAULT_PRIMARY_COLOR
    )
    secondary_color = models.CharField(
        max_length=7, default=DEFAULT_SECONDARY_COLOR
    )
    accent_color = models.CharField(
        max_length=7, default=DEFAULT_ACCENT_COLOR
    )

    # ----------------------------------------------------------------
    # Color extraction metadata
    # ----------------------------------------------------------------
    # These store the auto-detected colors so admin can compare/reset
    auto_primary_color = models.CharField(max_length=7, blank=True)
    auto_secondary_color = models.CharField(max_length=7, blank=True)
    auto_accent_color = models.CharField(max_length=7, blank=True)
    auto_palette = models.JSONField(default=list, blank=True)

    # ----------------------------------------------------------------
    # Timestamps
    # ----------------------------------------------------------------
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'School Settings'
        verbose_name_plural = 'School Settings'

    def __str__(self):
        return f'School Settings: {self.school_name}'

    # ----------------------------------------------------------------
    # Singleton helper
    # ----------------------------------------------------------------
    @classmethod
    def get_settings(cls):
        """
        Return the active SchoolSettings record, creating a default one
        if none exists yet. This ensures the site always has usable
        branding even before an admin configures it.
        """
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def has_logo(self):
        return bool(self.logo)

    @property
    def effective_primary(self):
        palette = self.effective_palette
        if self.logo and palette:
            return palette[0]
        return self.primary_color or DEFAULT_PRIMARY_COLOR

    @property
    def effective_secondary(self):
        palette = self.effective_palette
        if self.logo and len(palette) > 1:
            return palette[1]
        return self.secondary_color or DEFAULT_SECONDARY_COLOR

    @property
    def effective_accent(self):
        palette = self.effective_palette
        if self.logo and len(palette) > 2:
            return palette[2]
        return self.accent_color or DEFAULT_ACCENT_COLOR

    @property
    def effective_palette(self):
        palette = self.auto_palette or []
        if palette:
            return palette
        colors = (self.primary_color, self.secondary_color, self.accent_color)
        return list(dict.fromkeys(color for color in colors if color))
