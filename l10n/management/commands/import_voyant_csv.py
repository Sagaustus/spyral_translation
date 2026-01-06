from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from l10n.models import Locale, StringUnit, Translation


REQUIRED_COLUMNS = {"Location", "ID", "est"}
RTL_LEGACY_COLUMNS = {"ar", "fa", "ur", "he"}


COMMON_LOCALE_NAMES: dict[str, str] = {
    "en": "English",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "pt": "Portuguese",
    "it": "Italian",
    "hi": "Hindi",
    "yo": "Yoruba",
    "ar": "Arabic",
    "fa": "Persian",
    "ur": "Urdu",
    "he": "Hebrew",
    "cs": "Czech",
    "zh-hans": "Chinese (Simplified)",
}


def _strip_trailing_newlines(value: str | None) -> str:
    return (value or "").rstrip("\r\n")


def _extract_locale_code(header: str) -> str:
    """Extract a locale code from a column header.

    Accepts either raw codes (e.g., "fr") or labels like "French (fr)".
    """

    raw = (header or "").strip()
    if not raw:
        return ""
    match = re.search(r"\(([^()]+)\)\s*$", raw)
    if match:
        return match.group(1).strip()
    return raw


def _resolve_required_keys(fieldnames: list[str]) -> tuple[str, str, str, str]:
    by_lower: dict[str, str] = {name.strip().lower(): name for name in fieldnames}

    try:
        location_key = by_lower["location"]
        id_key = by_lower["id"]
        est_key = by_lower["est"]
    except KeyError as exc:
        raise CommandError("CSV missing required columns: Location, ID, est") from exc

    # "en" can be either a raw "en" header or something like "English (en)".
    en_key = by_lower.get("en")
    if not en_key:
        for name in fieldnames:
            if _extract_locale_code(name).strip().lower() == "en":
                en_key = name
                break

    if not en_key:
        raise CommandError(
            "CSV missing required English column: expected 'en' or a header like 'English (en)'."
        )

    return location_key, id_key, en_key, est_key


def _normalize_code(raw: str) -> str:
    code = (raw or "").strip().lower().replace("_", "-")
    code = code.replace(" ", "-")
    code = re.sub(r"[^a-z0-9-]+", "-", code)
    code = re.sub(r"-+", "-", code).strip("-")
    return code


@dataclass
class ImportCounts:
    rows_total: int = 0
    rows_skipped: int = 0
    rows_processed: int = 0

    stringunits_created: int = 0
    stringunits_updated: int = 0

    locales_created: int = 0
    locales_updated: int = 0

    translations_created: int = 0
    translations_updated: int = 0


def _upsert_locale(legacy_column: str, counts: ImportCounts) -> Locale:
    legacy_exact = legacy_column.strip()
    if not legacy_exact:
        raise CommandError("Encountered an empty locale column name in CSV header.")

    legacy_lower = legacy_exact.lower()

    if legacy_lower == "zh":
        code = "zh-hans"
        bcp47 = "zh-Hans"
    elif legacy_lower == "cz":
        code = "cs"
        bcp47 = "cs"
    else:
        code = _normalize_code(legacy_exact)
        if not code:
            raise CommandError(f"Invalid locale column name: {legacy_column!r}")
        bcp47 = code

    name = COMMON_LOCALE_NAMES.get(code) or code.upper()
    is_rtl = legacy_lower in RTL_LEGACY_COLUMNS

    locale, created = Locale.objects.get_or_create(
        code=code,
        defaults={
            "bcp47": bcp47,
            "name": name,
            "script": None,
            "is_rtl": is_rtl,
            "enabled": True,
            "legacy_column": legacy_exact,
        },
    )

    if created:
        counts.locales_created += 1
        return locale

    changed = False

    # Only backfill/normalize existing locales; avoid clobbering manual edits.
    if not (locale.legacy_column or "").strip():
        locale.legacy_column = legacy_exact
        changed = True

    if not (locale.bcp47 or "").strip():
        locale.bcp47 = bcp47
        changed = True

    if not (locale.name or "").strip() or locale.name == locale.code.upper():
        locale.name = name
        changed = True

    if is_rtl and not locale.is_rtl:
        locale.is_rtl = True
        changed = True

    if changed:
        locale.save(update_fields=["legacy_column", "bcp47", "name", "is_rtl"])
        counts.locales_updated += 1

    return locale


class Command(BaseCommand):
    help = "Import Voyant CSV into Locale/StringUnit/Translation tables (APPROVED + IMPORTED)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            required=True,
            help="Path to Voyant CSV file (e.g. data/voyant_strings.csv)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Parse and report counts but do not persist changes.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Only process first N valid rows (after skipping invalid rows).",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            dest="row_verbose",
            help="Print per-row actions (default is minimal).",
        )

    def handle(self, *args, **options):
        path = Path(options["path"]).expanduser()
        dry_run: bool = bool(options["dry_run"])
        limit: int | None = options.get("limit")
        row_verbose: bool = bool(options["row_verbose"])

        if limit is not None and limit < 0:
            raise CommandError("--limit must be >= 0")

        if not path.exists() or not path.is_file():
            raise CommandError(f"CSV file not found: {path}")

        counts = ImportCounts()

        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise CommandError("CSV has no header row.")

            fieldnames = [name.strip() for name in reader.fieldnames if name is not None]

            location_key, id_key, en_key, est_key = _resolve_required_keys(fieldnames)

            locale_headers = [
                name
                for name in fieldnames
                if name
                and name not in {location_key, id_key, en_key, est_key}
            ]

            with transaction.atomic():
                locales_by_header: dict[str, Locale] = {}
                for header in locale_headers:
                    legacy_code = _extract_locale_code(header)
                    locale = _upsert_locale(legacy_code, counts)
                    locales_by_header[header] = locale

                for row in reader:
                    counts.rows_total += 1

                    location = (row.get(location_key) or "").strip()
                    message_id = (row.get(id_key) or "").strip()

                    if not location or not message_id:
                        counts.rows_skipped += 1
                        continue

                    if limit is not None and counts.rows_processed >= limit:
                        break

                    source_text = _strip_trailing_newlines(row.get(en_key))
                    source_updated_on = (row.get(est_key) or "")

                    string_unit, created = StringUnit.objects.get_or_create(
                        location=location,
                        message_id=message_id,
                        defaults={
                            "source_text": source_text,
                            "source_updated_on": source_updated_on,
                        },
                    )

                    if created:
                        counts.stringunits_created += 1
                    else:
                        changed = False
                        if string_unit.source_text != source_text:
                            string_unit.source_text = source_text
                            changed = True
                        if string_unit.source_updated_on != source_updated_on:
                            string_unit.source_updated_on = source_updated_on
                            changed = True

                        if changed:
                            string_unit.save()
                            counts.stringunits_updated += 1

                    # Ensure source_hash is present (model computes on save).
                    if not string_unit.source_hash:
                        string_unit.save(update_fields=["source_hash"])

                    for header in locale_headers:
                        cell_text = _strip_trailing_newlines(row.get(header))
                        if not cell_text.strip():
                            continue

                        locale = locales_by_header[header]

                        tr, tr_created = Translation.objects.get_or_create(
                            string_unit=string_unit,
                            locale=locale,
                            defaults={
                                "approved_text": cell_text,
                                "status": Translation.TranslationStatus.APPROVED,
                                "provenance": Translation.TranslationProvenance.IMPORTED,
                                "source_hash_at_last_update": string_unit.source_hash,
                                "reviewer": None,
                            },
                        )

                        if tr_created:
                            counts.translations_created += 1
                            if row_verbose:
                                self.stdout.write(
                                    f"[create] {locale.code} {location}::{message_id}"
                                )
                            continue

                        update_fields: list[str] = []

                        if tr.approved_text != cell_text:
                            tr.approved_text = cell_text
                            update_fields.append("approved_text")

                        if tr.status != Translation.TranslationStatus.APPROVED:
                            tr.status = Translation.TranslationStatus.APPROVED
                            update_fields.append("status")

                        if tr.provenance != Translation.TranslationProvenance.IMPORTED:
                            tr.provenance = Translation.TranslationProvenance.IMPORTED
                            update_fields.append("provenance")

                        if tr.source_hash_at_last_update != string_unit.source_hash:
                            tr.source_hash_at_last_update = string_unit.source_hash
                            update_fields.append("source_hash_at_last_update")

                        if tr.reviewer_id is not None:
                            tr.reviewer = None
                            update_fields.append("reviewer")

                        # Do NOT touch reviewer_text or machine_draft.

                        if update_fields:
                            tr.save(update_fields=update_fields)
                            counts.translations_updated += 1
                            if row_verbose:
                                self.stdout.write(
                                    f"[update] {locale.code} {location}::{message_id}"
                                )

                    counts.rows_processed += 1

                if dry_run:
                    transaction.set_rollback(True)

        self.stdout.write(
            "\n".join(
                [
                    "Import summary:",
                    f"- rows_total: {counts.rows_total}",
                    f"- rows_skipped: {counts.rows_skipped}",
                    f"- rows_processed: {counts.rows_processed}",
                    f"- locales_created: {counts.locales_created}",
                    f"- locales_updated: {counts.locales_updated}",
                    f"- stringunits_created: {counts.stringunits_created}",
                    f"- stringunits_updated: {counts.stringunits_updated}",
                    f"- translations_created: {counts.translations_created}",
                    f"- translations_updated: {counts.translations_updated}",
                ]
            )
        )
