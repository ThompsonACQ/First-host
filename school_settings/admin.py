"""
Admin registration for SchoolSettings.
"""
from django.contrib import admin
from django.contrib import messages
from .branding import apply_default_branding, extract_colors_from_logo
from .models import SchoolSettings


@admin.register(SchoolSettings)
class SchoolSettingsAdmin(admin.ModelAdmin):
    list_display = ['school_name', 'primary_color', 'has_logo', 'updated_at']
    readonly_fields = [
        'auto_primary_color', 'auto_secondary_color', 'auto_accent_color',
        'auto_palette', 'created_at', 'updated_at',
    ]

    def save_model(self, request, obj, form, change):
        logo_changed = 'logo' in form.changed_data and obj.logo
        if logo_changed:
            colors = extract_colors_from_logo(obj.logo)
            if colors:
                palette = list(colors)
                primary = palette[0]
                secondary = palette[1] if len(palette) > 1 else primary
                accent = palette[2] if len(palette) > 2 else secondary
                obj.auto_palette = palette
                obj.primary_color = obj.auto_primary_color = primary
                obj.secondary_color = obj.auto_secondary_color = secondary
                obj.accent_color = obj.auto_accent_color = accent
            else:
                obj.auto_palette = []
                obj.auto_primary_color = ''
                obj.auto_secondary_color = ''
                obj.auto_accent_color = ''
                self.message_user(
                    request,
                    'Logo saved, but its colors could not be detected. Set the theme colors manually.',
                    level=messages.WARNING,
                )
        elif 'logo' in form.changed_data:
            apply_default_branding(obj)
        super().save_model(request, obj, form, change)

    def has_logo(self, obj):
        return bool(obj.logo)
    has_logo.boolean = True
    has_logo.short_description = 'Logo'
