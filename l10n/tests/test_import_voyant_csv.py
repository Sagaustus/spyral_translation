from __future__ import annotations

import csv

import pytest
from django.core.management import call_command

from l10n.models import Locale, StringUnit, Translation


def _write_csv(path, fieldnames, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


@pytest.mark.django_db
def test_import_creates_stringunit_and_translations(tmp_path):
    csv_path = tmp_path / "voyant.csv"
    fieldnames = ["Location", "ID", "en", "est", "fr", "zh", "cz"]

    _write_csv(
        csv_path,
        fieldnames,
        [
            {
                "Location": "ui",
                "ID": "hello",
                "en": "Hello",
                "est": "2026-01-01",
                "fr": "Bonjour",
                "zh": "\u4f60\u597d",
                "cz": "Ahoj",
            }
        ],
    )

    call_command("import_voyant_csv", path=str(csv_path))

    assert StringUnit.objects.count() == 1
    assert Translation.objects.count() == 3

    su = StringUnit.objects.get()
    assert su.location == "ui"
    assert su.message_id == "hello"
    assert su.source_text == "Hello"
    assert su.source_updated_on == "2026-01-01"
    assert su.source_hash

    fr = Locale.objects.get(code="fr")
    assert fr.legacy_column == "fr"

    zh = Locale.objects.get(code="zh-hans")
    assert zh.legacy_column == "zh"
    assert zh.bcp47 == "zh-Hans"

    cs = Locale.objects.get(code="cs")
    assert cs.legacy_column == "cz"
    assert cs.bcp47 == "cs"

    t_fr = Translation.objects.get(locale=fr, string_unit=su)
    assert t_fr.approved_text == "Bonjour"
    assert t_fr.status == Translation.TranslationStatus.APPROVED
    assert t_fr.provenance == Translation.TranslationProvenance.IMPORTED
    assert t_fr.source_hash_at_last_update == su.source_hash


@pytest.mark.django_db
def test_import_skips_missing_location_or_id(tmp_path):
    csv_path = tmp_path / "voyant.csv"
    fieldnames = ["Location", "ID", "en", "est", "fr"]

    _write_csv(
        csv_path,
        fieldnames,
        [
            {"Location": "", "ID": "x", "en": "Hello", "est": "", "fr": "Bonjour"},
            {"Location": "ui", "ID": "", "en": "Hello", "est": "", "fr": "Bonjour"},
            {"Location": "ui", "ID": "hello", "en": "Hello", "est": "", "fr": "Bonjour"},
        ],
    )

    call_command("import_voyant_csv", path=str(csv_path))

    assert StringUnit.objects.count() == 1
    assert Translation.objects.count() == 1


@pytest.mark.django_db
def test_import_is_idempotent_and_overwrites_approved_text(tmp_path):
    csv_path = tmp_path / "voyant.csv"
    fieldnames = ["Location", "ID", "en", "est", "fr"]

    _write_csv(
        csv_path,
        fieldnames,
        [
            {
                "Location": "ui",
                "ID": "hello",
                "en": "Hello",
                "est": "",
                "fr": "Bonjour",
            }
        ],
    )

    call_command("import_voyant_csv", path=str(csv_path))
    assert StringUnit.objects.count() == 1
    assert Translation.objects.count() == 1

    tr = Translation.objects.get()
    tr.reviewer_text = "Keep me"
    tr.machine_draft = "Keep me too"
    tr.save()

    # Idempotent re-run
    call_command("import_voyant_csv", path=str(csv_path))
    assert StringUnit.objects.count() == 1
    assert Translation.objects.count() == 1

    tr.refresh_from_db()
    assert tr.approved_text == "Bonjour"
    assert tr.reviewer_text == "Keep me"
    assert tr.machine_draft == "Keep me too"

    # Overwrite approved_text when the CSV changes
    _write_csv(
        csv_path,
        fieldnames,
        [
            {
                "Location": "ui",
                "ID": "hello",
                "en": "Hello",
                "est": "",
                "fr": "Salut",
            }
        ],
    )

    call_command("import_voyant_csv", path=str(csv_path))

    tr.refresh_from_db()
    assert tr.approved_text == "Salut"
    assert tr.reviewer_text == "Keep me"
    assert tr.machine_draft == "Keep me too"


@pytest.mark.django_db
def test_import_accepts_parenthetical_headers(tmp_path):
    csv_path = tmp_path / "voyant.csv"
    fieldnames = [
        "est",
        "Location",
        "ID",
        "English (en)",
        "French (fr)",
        "Mandarin (zh)",
        "Czech (cz)",
    ]

    _write_csv(
        csv_path,
        fieldnames,
        [
            {
                "est": "2026-01-01",
                "Location": "ui",
                "ID": "hello",
                "English (en)": "Hello",
                "French (fr)": "Bonjour",
                "Mandarin (zh)": "\u4f60\u597d",
                "Czech (cz)": "Ahoj",
            }
        ],
    )

    call_command("import_voyant_csv", path=str(csv_path))

    assert Locale.objects.filter(code="fr").exists()
    assert Locale.objects.filter(code="zh-hans", bcp47="zh-Hans").exists()
    assert Locale.objects.filter(code="cs", bcp47="cs", legacy_column="cz").exists()
    assert Translation.objects.count() == 3
