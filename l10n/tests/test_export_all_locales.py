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
def test_export_all_locales_creates_one_file_per_enabled_locale(tmp_path):
    fr = Locale.objects.create(code="fr", bcp47="fr", name="French", enabled=True)
    yo = Locale.objects.create(code="yo", bcp47="yo", name="Yoruba", enabled=True)

    su1 = StringUnit.objects.create(location="a", message_id="1", source_text="Hello")
    su2 = StringUnit.objects.create(location="a", message_id="2", source_text="World")
    su3 = StringUnit.objects.create(location="b", message_id="3", source_text="!")

    Translation.objects.create(
        string_unit=su1,
        locale=fr,
        approved_text="Pele",
        status=Translation.TranslationStatus.APPROVED,
    )
    Translation.objects.create(
        string_unit=su2,
        locale=fr,
        approved_text="Monde",
        status=Translation.TranslationStatus.APPROVED,
    )
    Translation.objects.create(
        string_unit=su1,
        locale=yo,
        approved_text="Pb",
        status=Translation.TranslationStatus.APPROVED,
    )

    out_dir = tmp_path / "exports"
    call_command("export_all_locales", out=str(out_dir))

    fr_path = out_dir / "voyant_fr.csv"
    yo_path = out_dir / "voyant_yo.csv"

    assert fr_path.exists()
    assert yo_path.exists()

    fr_rows = _read_csv(fr_path)
    yo_rows = _read_csv(yo_path)

    assert len(fr_rows) == 4  # header + 3 StringUnits
    assert len(yo_rows) == 4  # header + 3 StringUnits


@pytest.mark.django_db
def test_export_all_locales_locales_arg_restricts(tmp_path):
    Locale.objects.create(code="fr", bcp47="fr", name="French", enabled=True)
    Locale.objects.create(code="yo", bcp47="yo", name="Yoruba", enabled=True)
    StringUnit.objects.create(location="a", message_id="1", source_text="Hello")

    out_dir = tmp_path / "exports"
    call_command("export_all_locales", out=str(out_dir), locales="fr")

    assert (out_dir / "voyant_fr.csv").exists()
    assert not (out_dir / "voyant_yo.csv").exists()


@pytest.mark.django_db
def test_export_all_locales_missing_locale_returns_nonzero_but_exports_others(tmp_path):
    Locale.objects.create(code="fr", bcp47="fr", name="French", enabled=True)
    StringUnit.objects.create(location="a", message_id="1", source_text="Hello")

    out_dir = tmp_path / "exports"

    with pytest.raises(CommandError):
        call_command("export_all_locales", out=str(out_dir), locales="fr,missing")

    assert (out_dir / "voyant_fr.csv").exists()
