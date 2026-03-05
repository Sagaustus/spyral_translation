from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("l10n", "0003_translation_qa_flags"),
    ]

    operations = [
        migrations.AddField(
            model_name="translation",
            name="back_translation",
            field=models.TextField(
                blank=True,
                null=True,
                help_text="Machine draft translated back to English (for similarity scoring).",
            ),
        ),
        migrations.AddField(
            model_name="translation",
            name="similarity_score",
            field=models.FloatField(
                blank=True,
                null=True,
                help_text=(
                    "Cosine similarity between source and back-translation (0–1). "
                    "Below threshold → QA warning."
                ),
            ),
        ),
        migrations.AddField(
            model_name="translation",
            name="engine",
            field=models.CharField(
                blank=True,
                max_length=64,
                help_text="Translation engine that produced machine_draft, e.g. nllb-200-distilled-600M.",
            ),
        ),
    ]
