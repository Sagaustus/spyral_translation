from __future__ import annotations

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("l10n", "0003_translation_qa_flags"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TranslatorApplication",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("full_name", models.CharField(max_length=200)),
                ("affiliation", models.CharField(blank=True, max_length=255)),
                ("current_country", models.CharField(blank=True, max_length=2)),
                ("home_country", models.CharField(blank=True, max_length=2)),
                ("first_language", models.CharField(blank=True, max_length=16)),
                ("second_language", models.CharField(blank=True, max_length=16)),
                ("dialect", models.CharField(blank=True, max_length=100)),
                ("wants_acknowledgement", models.BooleanField(default=True)),
                ("acknowledgement_name", models.CharField(blank=True, max_length=200)),
                (
                    "status",
                    models.CharField(
                        choices=[("PENDING", "Pending"), ("APPROVED", "Approved"), ("REJECTED", "Rejected")],
                        default="PENDING",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "desired_locale",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="applications", to="l10n.locale"),
                ),
                (
                    "user",
                    models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="translator_application", to=settings.AUTH_USER_MODEL),
                ),
            ],
        ),
    ]
