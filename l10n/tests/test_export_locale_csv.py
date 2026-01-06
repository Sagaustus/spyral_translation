from __future__ import annotations

import csv

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from l10n.models import Locale, StringUnit, Translation


def _read_csv(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


@pytest.mark.django_db
def test_export_locale_csv_schema_and_rows(tmp_path):
    fr = Locale.objects.create(code="fr", bcp47="fr", name="French")

    su1 = StringUnit.objects.create(location="a", message_id="1", source_text="Hello")
    su2 = StringUnit.objects.create(location="a", message_id="2", source_text="World")
    su3 = StringUnit.objects.create(location="b", message_id="3", source_text="!")

    Translation.objects.create(
        string_unit=su1,
        locale=fr,
        approved_text="Bonjour",
        status=Translation.TranslationStatus.APPROVED,
    )
    Translation.objects.create(
        string_unit=su2,
        locale=fr,
        approved_text="Monde",
        status=Translation.TranslationStatus.APPROVED,
    )
    # su3 intentionally missing

    out_dir = tmp_path / "exports"
    call_command("export_locale_csv", locale="fr", out=str(out_dir))

    out_path = out_dir / "voyant_fr.csv"
    assert out_path.exists()

    rows = _read_csv(out_path)
    assert rows[0] == [
        "location",
        "message_id",
        "source_en",
        "target_locale",
        "translation",
        "status",
        "source_hash",
        "translation_updated_at",
    ]

    # 3 StringUnits + header
    assert len(rows) == 4

    data = rows[1:]
    assert data[0][0:2] == ["a", "1"]
    assert data[1][0:2] == ["a", "2"]
    assert data[2][0:2] == ["b", "3"]

    # Approved rows
    assert data[0][5] == "APPROVED"
    assert data[0][4] == "Bonjour"
    assert data[1][5] == "APPROVED"
    assert data[1][4] == "Monde"

    # Missing row
    assert data[2][5] == "MISSING"
    assert data[2][4] == ""


@pytest.mark.django_db
def test_export_locale_csv_only_missing(tmp_path):
    fr = Locale.objects.create(code="fr", bcp47="fr", name="French")

    su1 = StringUnit.objects.create(location="a", message_id="1", source_text="Hello")
    su2 = StringUnit.objects.create(location="a", message_id="2", source_text="World")

    Translation.objects.create(
        string_unit=su1,
        locale=fr,
        approved_text="Bonjour",
        status=Translation.TranslationStatus.APPROVED,
    )

    out_dir = tmp_path / "exports"
    call_command("export_locale_csv", locale="fr", out=str(out_dir), only_missing=True)

    out_path = out_dir / "voyant_fr.csv"
    rows = _read_csv(out_path)

    # header + 1 missing row
    assert len(rows) == 2
    assert rows[1][0:2] == ["a", "2"]
    assert rows[1][5] == "MISSING"


@pytest.mark.django_db
def test_export_missing_locale_raises(tmp_path):
    out_dir = tmp_path / "exports"

    with pytest.raises(CommandError):
        call_command("export_locale_csv", locale="does-not-exist", out=str(out_dir))
