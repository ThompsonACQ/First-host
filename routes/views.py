"""
Routes views — admin CRUD for routes and stops.
"""
from django import forms
from django.contrib import messages
from django.forms import inlineformset_factory, BaseInlineFormSet
from django.shortcuts import render, redirect, get_object_or_404

from .models import Route, RouteStop
from accounts.decorators import admin_required


class RouteForm(forms.ModelForm):
    class Meta:
        model = Route
        fields = [
            'name', 'description',
            'start_location', 'start_latitude', 'start_longitude',
            'destination', 'destination_latitude', 'destination_longitude',
            'active',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
        }


class RouteStopForm(forms.ModelForm):
    """
    Custom form for each stop row.
    A row is treated as empty (silently skipped) when 'name' is blank,
    so extra unused rows never cause unique_together validation errors.
    """
    class Meta:
        model = RouteStop
        fields = ['name', 'latitude', 'longitude', 'stop_order']

    def has_changed(self):
        # If name is blank, treat the whole row as unchanged so Django skips it.
        name_value = self.data.get(self.add_prefix('name'), '').strip()
        if not name_value:
            return False
        return super().has_changed()


RouteStopFormSet = inlineformset_factory(
    Route, RouteStop,
    form=RouteStopForm,
    fields=['name', 'latitude', 'longitude', 'stop_order'],
    extra=1,          # Only 1 blank extra row to reduce clutter
    can_delete=True,
)


@admin_required
def route_list(request):
    routes = Route.objects.prefetch_related('stops').order_by('name')
    return render(request, 'routes/route_list.html', {'routes': routes})


@admin_required
def route_create(request):
    if request.method == 'POST':
        form = RouteForm(request.POST)
        formset = RouteStopFormSet(request.POST, prefix='stops')
        if form.is_valid() and formset.is_valid():
            route = form.save()
            formset.instance = route
            formset.save()
            messages.success(request, f'Route "{route.name}" created.')
            return redirect('routes:route_list')
        else:
            # Surface errors as flash messages so admin can see what went wrong
            if not form.is_valid():
                messages.error(request, f'Route form errors: {form.errors.as_text()}')
            if not formset.is_valid():
                for i, err in enumerate(formset.errors):
                    if err:
                        messages.error(request, f'Stop row {i + 1} errors: {err}')
                nfe = formset.non_form_errors()
                if nfe:
                    messages.error(request, f'Stops error: {nfe}')
    else:
        form = RouteForm()
        formset = RouteStopFormSet(prefix='stops')
    return render(request, 'routes/route_form.html', {
        'form': form,
        'formset': formset,
        'title': 'Add Route',
    })


@admin_required
def route_edit(request, pk):
    route = get_object_or_404(Route, pk=pk)
    if request.method == 'POST':
        form = RouteForm(request.POST, instance=route)
        formset = RouteStopFormSet(request.POST, instance=route, prefix='stops')
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, f'Route "{route.name}" updated.')
            return redirect('routes:route_list')
        else:
            if not form.is_valid():
                messages.error(request, f'Route form errors: {form.errors.as_text()}')
            if not formset.is_valid():
                for i, err in enumerate(formset.errors):
                    if err:
                        messages.error(request, f'Stop row {i + 1} errors: {err}')
                nfe = formset.non_form_errors()
                if nfe:
                    messages.error(request, f'Stops error: {nfe}')
    else:
        form = RouteForm(instance=route)
        formset = RouteStopFormSet(instance=route, prefix='stops')
    return render(request, 'routes/route_form.html', {
        'form': form,
        'formset': formset,
        'title': f'Edit Route: {route.name}',
        'route': route,
    })


@admin_required
def route_toggle_active(request, pk):
    route = get_object_or_404(Route, pk=pk)
    route.active = not route.active
    route.save(update_fields=['active'])
    status = 'activated' if route.active else 'deactivated'
    messages.success(request, f'Route "{route.name}" {status}.')
    return redirect('routes:route_list')


@admin_required
def route_delete(request, pk):
    route = get_object_or_404(Route, pk=pk)
    if request.method == 'POST':
        name = route.name
        route.delete()
        messages.success(request, f'Route "{name}" deleted.')
        return redirect('routes:route_list')
    return render(request, 'routes/route_confirm_delete.html', {'route': route})
