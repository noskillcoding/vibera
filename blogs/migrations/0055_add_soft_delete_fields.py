# Generated manually for soft delete functionality

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('blogs', '0054_dangerousreport'),
    ]

    operations = [
        migrations.AddField(
            model_name='comment',
            name='deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='comment',
            name='deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='dangerousreport',
            name='deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='dangerousreport',
            name='deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]