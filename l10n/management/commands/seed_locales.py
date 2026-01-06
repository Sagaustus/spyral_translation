from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from l10n.models import Locale
from l10n.services.locale_presets import LOCALE_PRESETS, PRESET_GLOBAL_PLUS_AFRICA_INDIA_CHINESE


class Command(BaseCommand):
    help = "Seed curated Locale rows into the DB (disabled by default)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--preset",
            required=True,
            help=f"Preset name (only supported: {PRESET_GLOBAL_PLUS_AFRICA_INDIA_CHINESE})",
        )
        parser.add_argument(
            "--enable",
            action="store_true",
            dest="enable",
            help="If set, seed locales with enabled=True (default False).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Show what would change without writing to the DB.",
        )

    def handle(self, *args, **options):
        preset = str(options["preset"]).strip()
        if preset != PRESET_GLOBAL_PLUS_AFRICA_INDIA_CHINESE:
            raise CommandError(
                f"Unsupported preset: {preset}. Only '{PRESET_GLOBAL_PLUS_AFRICA_INDIA_CHINESE}' is allowed."
            )

        enable: bool = bool(options["enable"])
        dry_run: bool = bool(options["dry_run"])

        seeds = LOCALE_PRESETS.get(preset, [])
        if not seeds:
            self.stdout.write("No locales to seed.")
            return

        created_count = 0
        updated_count = 0
        skipped_count = 0
        created_codes: list[str] = []

        with transaction.atomic():
            for seed in seeds:
                locale, created = Locale.objects.get_or_create(
                    code=seed.code,
                    defaults={
                        "bcp47": seed.bcp47,
                        "name": seed.name,
                        "script": seed.script,
                        "is_rtl": seed.is_rtl,
                        "enabled": enable,
                    },
                )

                if created:
                    created_count += 1
                    created_codes.append(locale.code)
                    continue

                changed_fields: list[str] = []

                if locale.bcp47 != seed.bcp47:
                    locale.bcp47 = seed.bcp47
                    changed_fields.append("bcp47")

                if locale.name != seed.name:
                    locale.name = seed.name
                    changed_fields.append("name")

                if locale.script != seed.script:
                    locale.script = seed.script
                    changed_fields.append("script")

                if locale.is_rtl != seed.is_rtl:
                    locale.is_rtl = seed.is_rtl
                    changed_fields.append("is_rtl")

                if locale.enabled != enable:
                    locale.enabled = enable
                    changed_fields.append("enabled")

                # Do NOT overwrite legacy_column if it already exists.
                # (We intentionally do not set legacy_column from presets.)

                if changed_fields:
                    locale.save(update_fields=changed_fields)
                    updated_count += 1
                else:
                    skipped_count += 1

            if dry_run:
                transaction.set_rollback(True)

        created_preview = ", ".join(created_codes[:12])
        if len(created_codes) > 12:
            created_preview += f" …(+{len(created_codes) - 12} more)"

        self.stdout.write("Seed summary:")
        self.stdout.write(f"- created_count: {created_count}")
        self.stdout.write(f"- updated_count: {updated_count}")
        self.stdout.write(f"- skipped_count: {skipped_count}")
        self.stdout.write(f"- created_codes: {created_preview}")
        if dry_run:
            self.stdout.write("(dry-run: no changes were written)")
