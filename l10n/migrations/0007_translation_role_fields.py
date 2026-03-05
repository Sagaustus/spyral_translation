from __future__ import annotations

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("l10n", "0006_merge_0004_translation_pipeline_fields_0005_translatorapplication_photo"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="translation",
            name="translator_text",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="translation",
            name="translator",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="l10n_translations_translated",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="translation",
            name="approved_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="l10n_translations_approved",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="translation",
            name="approved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
