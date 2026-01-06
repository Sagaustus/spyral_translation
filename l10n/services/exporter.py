from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from django.core.management.base import CommandError

from l10n.models import Locale, StringUnit, Translation


@dataclass(frozen=True)
class ExportStats:
    total_string_units: int
    approved_count: int
    missing_count: int
    output_path: Path


def _is_nonempty(value: str | None) -> bool:
    return bool((value or "").strip())


def export_locale_csv(
    *,
    locale_code: str,
    out_dir: Path,
    include_source_updated: bool = False,
    missing_marker: str = "",
    only_missing: bool = False,
) -> ExportStats:
    """Export one locale to a CSV with a uniform schema.

    Raises CommandError if the locale does not exist.
    """

    try:
        locale = Locale.objects.get(code=locale_code)
    except Locale.DoesNotExist as exc:
        raise CommandError(f"Locale not found: {locale_code}") from exc

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CommandError(f"Could not create output directory: {out_dir}") from exc

    output_path = out_dir / f"voyant_{locale_code}.csv"

    header = [
        "location",
        "message_id",
        "source_en",
        "target_locale",
        "translation",
        "status",
        "source_hash",
        "translation_updated_at",
    ]
    if include_source_updated:
        header.append("source_updated_on")

    # Preload translations for this locale to avoid N+1.
    translations_by_string_unit_id: dict[int, dict[str, object]] = {}
    for row in (
        Translation.objects.filter(locale=locale)
        .values("string_unit_id", "approved_text", "updated_at")
        .iterator()
    ):
        translations_by_string_unit_id[int(row["string_unit_id"])] = row

    stringunits_qs = (
        StringUnit.objects.all()
        .order_by("location", "message_id")
        .only(
            "id",
            "location",
            "message_id",
            "source_text",
            "source_hash",
            "source_updated_on",
        )
    )

    total_string_units = 0
    approved_count = 0
    missing_count = 0

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        for su in stringunits_qs.iterator():
            total_string_units += 1
            tr_row = translations_by_string_unit_id.get(su.id)
            approved_text = None
            updated_at = None
            if tr_row:
                approved_text = tr_row.get("approved_text")  # type: ignore[assignment]
                updated_at = tr_row.get("updated_at")

            has_approved = _is_nonempty(approved_text)

            if has_approved:
                status = "APPROVED"
                translation_value = str(approved_text)
                translation_updated_at = updated_at.isoformat() if updated_at else ""
                approved_count += 1
            else:
                status = "MISSING"
                translation_value = missing_marker
                translation_updated_at = ""
                missing_count += 1

            if only_missing and status != "MISSING":
                continue

            row_out = [
                su.location,
                su.message_id,
                su.source_text,
                locale_code,
                translation_value,
                status,
                su.source_hash,
                translation_updated_at,
            ]

            if include_source_updated:
                row_out.append(su.source_updated_on)

            writer.writerow(row_out)

    return ExportStats(
        total_string_units=total_string_units,
        approved_count=approved_count,
        missing_count=missing_count,
        output_path=output_path,
    )
