"""
Buses views — admin CRUD for buses.
"""
from django import forms
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404

from .models import Bus
from accounts.decorators import admin_required
from accounts.models import User
from routes.models import Route


class BusForm(forms.ModelForm):
    class Meta:
        model = Bus
        fields = [
            'bus_number', 'registration_number', 'description',
            'driver', 'route', 'capacity', 'active',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only allow drivers in the driver dropdown
        self.fields['driver'].queryset = User.objects.filter(role=User.ROLE_DRIVER, is_active=True)
        self.fields['route'].queryset = Route.objects.filter(active=True)
        self.fields['driver'].empty_label = '— No driver assigned —'
        self.fields['route'].empty_label = '— No route assigned —'


@admin_required
def bus_list(request):
    buses = Bus.objects.select_related('driver', 'route').order_by('bus_number')
    return render(request, 'buses/bus_list.html', {'buses': buses})


@admin_required
def bus_create(request):
    if request.method == 'POST':
        form = BusForm(request.POST)
        if form.is_valid():
            bus = form.save()
            messages.success(request, f'Bus {bus.bus_number} created.')
            return redirect('buses:bus_list')
    else:
        form = BusForm()
    return render(request, 'buses/bus_form.html', {'form': form, 'title': 'Add Bus'})


@admin_required
def bus_edit(request, pk):
    bus = get_object_or_404(Bus, pk=pk)
    if request.method == 'POST':
        form = BusForm(request.POST, instance=bus)
        if form.is_valid():
            form.save()
            messages.success(request, f'Bus {bus.bus_number} updated.')
            return redirect('buses:bus_list')
    else:
        form = BusForm(instance=bus)
    return render(request, 'buses/bus_form.html', {
        'form': form,
        'title': f'Edit Bus {bus.bus_number}',
        'bus': bus,
    })


@admin_required
def bus_toggle_active(request, pk):
    bus = get_object_or_404(Bus, pk=pk)
    bus.active = not bus.active
    if not bus.active:
        bus.status = Bus.STATUS_OFFLINE
    bus.save(update_fields=['active', 'status'])
    status = 'activated' if bus.active else 'deactivated'
    messages.success(request, f'Bus {bus.bus_number} {status}.')
    return redirect('buses:bus_list')


@admin_required
def bus_delete(request, pk):
    bus = get_object_or_404(Bus, pk=pk)
    if request.method == 'POST':
        bus_number = bus.bus_number
        bus.delete()
        messages.success(request, f'Bus {bus_number} deleted.')
        return redirect('buses:bus_list')
    return render(request, 'buses/bus_confirm_delete.html', {'bus': bus})
