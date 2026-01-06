from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from l10n.models import Locale
from l10n.services.exporter import export_locale_csv


def _parse_locales_arg(value: str) -> list[str]:
    parts = [p.strip() for p in (value or "").split(",")]
    return [p for p in parts if p]


class Command(BaseCommand):
    help = "Export CSV files for all enabled locales using the same schema as export_locale_csv."

    def add_arguments(self, parser):
        parser.add_argument(
            "--out",
            required=True,
            help="Output directory (created if missing)",
        )
        parser.add_argument(
            "--include-source-updated",
            action="store_true",
            dest="include_source_updated",
            help="Include source_updated_on column.",
        )
        parser.add_argument(
            "--missing-marker",
            default="",
            help="String to use for missing translations (default empty string).",
        )
        parser.add_argument(
            "--only-missing",
            action="store_true",
            dest="only_missing",
            help="Export only rows where the approved translation is missing.",
        )
        parser.add_argument(
            "--locales",
            default=None,
            help="Optional comma-separated locale codes to export (e.g. 'fr,yo,zh-hans').",
        )

    def handle(self, *args, **options):
        out_dir = Path(str(options["out"])).expanduser()
        include_source_updated: bool = bool(options["include_source_updated"])
        missing_marker: str = str(options["missing_marker"])
        only_missing: bool = bool(options["only_missing"])
        locales_arg: str | None = options.get("locales")

        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CommandError(f"Could not create output directory: {out_dir}") from exc

        missing_requested: list[str] = []

        if locales_arg:
            requested_codes = _parse_locales_arg(str(locales_arg))
            locales = list(Locale.objects.filter(code__in=requested_codes))
            existing_codes = {l.code for l in locales}
            missing_requested = [c for c in requested_codes if c not in existing_codes]

            for loc in locales:
                if not loc.enabled:
                    self.stderr.write(
                        f"Warning: locale {loc.code} is disabled but will be exported due to --locales."
                    )

            locales_to_export = sorted(locales, key=lambda l: l.code)
        else:
            locales_to_export = list(Locale.objects.filter(enabled=True).order_by("code"))

        if not locales_to_export:
            self.stdout.write("No locales to export.")
            return

        exported_count = 0
        total_approved = 0
        total_missing = 0

        for loc in locales_to_export:
            stats = export_locale_csv(
                locale_code=loc.code,
                out_dir=out_dir,
                include_source_updated=include_source_updated,
                missing_marker=missing_marker,
                only_missing=only_missing,
            )

            exported_count += 1
            total_approved += stats.approved_count
            total_missing += stats.missing_count

            self.stdout.write(
                f"{loc.code}: approved={stats.approved_count} missing={stats.missing_count} -> {stats.output_path}"
            )

        self.stdout.write(
            "\n".join(
                [
                    "Final summary:",
                    f"- locales_exported: {exported_count}",
                    f"- total_approved: {total_approved}",
                    f"- total_missing: {total_missing}",
                    f"- output_directory: {out_dir}",
                ]
            )
        )

        if missing_requested:
            self.stderr.write(
                "Missing locale(s) requested via --locales: " + ", ".join(missing_requested)
            )
            raise CommandError("One or more requested locales do not exist.")
