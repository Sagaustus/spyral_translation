from __future__ import annotations

import pytest
from django.core.management import call_command

from l10n.models import Locale
from l10n.services.locale_presets import LOCALE_PRESETS, PRESET_GLOBAL_PLUS_AFRICA_INDIA_CHINESE


def _parse_counts(output: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("- created_count:"):
            counts["created"] = int(line.split(":", 1)[1].strip())
        if line.startswith("- updated_count:"):
            counts["updated"] = int(line.split(":", 1)[1].strip())
        if line.startswith("- skipped_count:"):
            counts["skipped"] = int(line.split(":", 1)[1].strip())
    return counts


@pytest.mark.django_db
def test_seed_locales_is_idempotent_defaults_disabled(capsys):
    preset_size = len(LOCALE_PRESETS[PRESET_GLOBAL_PLUS_AFRICA_INDIA_CHINESE])

    call_command("seed_locales", preset=PRESET_GLOBAL_PLUS_AFRICA_INDIA_CHINESE)
    out1 = capsys.readouterr().out
    c1 = _parse_counts(out1)

    assert Locale.objects.count() == preset_size
    assert Locale.objects.filter(enabled=True).count() == 0
    assert c1["created"] == preset_size

    call_command("seed_locales", preset=PRESET_GLOBAL_PLUS_AFRICA_INDIA_CHINESE)
    out2 = capsys.readouterr().out
    c2 = _parse_counts(out2)

    assert Locale.objects.count() == preset_size
    assert c2["created"] == 0


@pytest.mark.django_db
def test_seed_locales_enable_flag_sets_enabled_true():
    call_command(
        "seed_locales",
        preset=PRESET_GLOBAL_PLUS_AFRICA_INDIA_CHINESE,
        enable=True,
    )

    assert Locale.objects.count() == len(LOCALE_PRESETS[PRESET_GLOBAL_PLUS_AFRICA_INDIA_CHINESE])
    assert Locale.objects.filter(enabled=True).count() == Locale.objects.count()


@pytest.mark.django_db
def test_seed_locales_preserves_legacy_column():
    Locale.objects.create(
        code="yo",
        bcp47="yo",
        name="Old Yoruba",
        script="Latn",
        enabled=True,
        legacy_column="yo_legacy",
    )

    call_command("seed_locales", preset=PRESET_GLOBAL_PLUS_AFRICA_INDIA_CHINESE)

    yo = Locale.objects.get(code="yo")
    assert yo.legacy_column == "yo_legacy"
    assert yo.name == "Yoruba"  # updated from preset
    assert yo.enabled is False
