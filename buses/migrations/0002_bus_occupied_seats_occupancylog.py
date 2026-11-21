from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('buses', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='bus',
            name='occupied_seats',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.CreateModel(
            name='OccupancyLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('previous_occupied', models.PositiveIntegerField()),
                ('occupied_seats', models.PositiveIntegerField()),
                ('recorded_at', models.DateTimeField(auto_now_add=True)),
                ('bus', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='occupancy_logs', to='buses.bus')),
                ('driver', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='occupancy_updates', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-recorded_at']},
        ),
    ]
