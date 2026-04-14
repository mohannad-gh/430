from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_teamjoinrequest'),
    ]

    operations = [
        migrations.CreateModel(
            name='TeamLeaveRequest',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('accepted', 'Accepted'), ('rejected', 'Rejected')], default='pending', max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('team', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='leave_requests', to='core.team')),
                ('player', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='team_leave_requests', to=settings.AUTH_USER_MODEL)),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_leave_requests', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'unique_together': {('team', 'player')},
            },
        ),
    ]
