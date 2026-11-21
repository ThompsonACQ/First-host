"""
Context processor — injects school_settings into every template context.
This allows all templates to access school branding without repetitive view code.
"""

from .models import SchoolSettings


def _rgb_components(color):
    try:
        if len(color) != 7 or color[0] != '#':
            raise ValueError
        return ', '.join(str(int(color[index:index + 2], 16)) for index in (1, 3, 5))
    except (TypeError, ValueError):
        return '15, 23, 42'


def school_settings_processor(request):
    """
    Returns the active SchoolSettings so templates can use:
        {{ school.school_name }}, {{ school.logo }}, etc.
    """
    school = SchoolSettings.get_settings()
    palette = school.effective_palette or [
        school.effective_primary,
        school.effective_secondary,
        school.effective_accent,
    ]
    palette_slots = [palette[index % len(palette)] for index in range(6)]
    return {
        'school': school,
        'primary_color': school.effective_primary,
        'secondary_color': school.effective_secondary,
        'accent_color': school.effective_accent,
        'primary_rgb': _rgb_components(school.effective_primary),
        'secondary_rgb': _rgb_components(school.effective_secondary),
        'accent_rgb': _rgb_components(school.effective_accent),
        'logo_palette': palette,
        'brand_palette_slots': palette_slots,
    }
