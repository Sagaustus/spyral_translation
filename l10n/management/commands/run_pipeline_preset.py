from __future__ import annotations

from dataclasses import dataclass

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from l10n.models import Locale
from l10n.services.locale_presets import (
    LOCALE_PRESETS,
    PRESET_GLOBAL_PLUS_AFRICA_INDIA_CHINESE,
)


AFRICA_LOCALE_CODES = {
    "sw",
    "am",
    "ha",
    "yo",
    "ig",
    "zu",
    "xh",
    "so",
    "ti",
    "rw",
    "sn",
}


@dataclass
class RunStats:
    locales_processed: int = 0
    locales_failed: int = 0


class Command(BaseCommand):
    help = "Run the AI translation pipeline across a locale preset (optionally Africa-only)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--preset",
            default=PRESET_GLOBAL_PLUS_AFRICA_INDIA_CHINESE,
            help=f"Locale preset key (default {PRESET_GLOBAL_PLUS_AFRICA_INDIA_CHINESE}).",
        )
        parser.add_argument(
            "--only-africa",
            action="store_true",
            dest="only_africa",
            help="Only process locales in the Africa subset of the preset.",
        )
        parser.add_argument(
            "--engine",
            default="nllb",
            help='Engine: "nllb" | "openai" | "ollama" (default nllb).',
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Per-locale limit (0 means no limit).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-translate strings that already have a draft.",
        )
        parser.add_argument(
            "--no-score",
            action="store_true",
            dest="no_score",
            help="Skip back-translation + similarity scoring.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Compute and print what would happen without writing drafts.",
        )

    def handle(self, *args, **options):
        preset_key: str = str(options["preset"])
        only_africa: bool = bool(options["only_africa"])
        engine: str = str(options["engine"]).strip().lower()
        limit: int = int(options["limit"])
        force: bool = bool(options["force"])
        no_score: bool = bool(options["no_score"])
        dry_run: bool = bool(options["dry_run"])

        seeds = LOCALE_PRESETS.get(preset_key)
        if not seeds:
            raise CommandError(
                f"Unknown preset: {preset_key}. Available: {', '.join(sorted(LOCALE_PRESETS.keys()))}"
            )

        locale_codes = [seed.code for seed in seeds]
        if only_africa:
            locale_codes = [code for code in locale_codes if code in AFRICA_LOCALE_CODES]

        if not locale_codes:
            self.stdout.write("No locales selected.")
            return

        stats = RunStats()

        for seed in seeds:
            if seed.code not in locale_codes:
                continue

            locale, _ = Locale.objects.get_or_create(
                code=seed.code,
                defaults={
                    "bcp47": seed.bcp47,
                    "name": seed.name,
                    "script": seed.script,
                    "is_rtl": seed.is_rtl,
                    "enabled": True,
                },
            )

            if not locale.enabled:
                locale.enabled = True
                locale.save(update_fields=["enabled"])

            self.stdout.write(f"\n=== {locale.code} ({locale.name}) ===")
            try:
                call_command(
                    "run_pipeline",
                    locale=locale.code,
                    engine=engine,
                    limit=limit,
                    force=force,
                    no_score=no_score,
                    dry_run=dry_run,
                    verbosity=max(int(self.verbosity), 1),
                )
                stats.locales_processed += 1
            except Exception as exc:  # noqa: BLE001
                stats.locales_failed += 1
                self.stderr.write(f"Error for {locale.code}: {exc}")

        self.stdout.write(
            "\n".join(
                [
                    "\nPreset run summary:",
                    f"- locales_processed: {stats.locales_processed}",
                    f"- locales_failed: {stats.locales_failed}",
                ]
            )
        )
