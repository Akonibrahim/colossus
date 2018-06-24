# Generated by Django 2.0.6 on 2018-06-24 17:05

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0004_auto_20180622_1649'),
        ('templates', '0002_emailtemplate_last_used_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='emailtemplate',
            name='last_used_campaign',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='campaigns.Campaign', verbose_name='last used campaign'),
        ),
    ]
