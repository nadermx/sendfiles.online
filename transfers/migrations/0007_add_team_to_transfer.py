from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
        ('transfers', '0006_add_security_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='transfer',
            name='team',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='transfers',
                to='accounts.team',
            ),
        ),
        migrations.AddField(
            model_name='transfer',
            name='visibility',
            field=models.CharField(
                choices=[
                    ('private', 'Private'),
                    ('team', 'Team'),
                    ('public', 'Public'),
                ],
                default='private',
                max_length=20,
            ),
        ),
        migrations.AddIndex(
            model_name='transfer',
            index=models.Index(fields=['team', 'created_at'], name='transfers_t_team_id_8b9c3f_idx'),
        ),
    ]
