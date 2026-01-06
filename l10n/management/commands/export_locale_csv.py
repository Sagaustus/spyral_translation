from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from l10n.services.exporter import export_locale_csv


class Command(BaseCommand):
    help = "Export a single locale to a uniform CSV schema using approved translations only."

    def add_arguments(self, parser):
        parser.add_argument(
            "--locale",
            required=True,
            help="Locale.code to export (e.g., fr, yo, zh-hans)",
        )
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

    def handle(self, *args, **options):
        locale_code: str = str(options["locale"])
        out_dir = Path(str(options["out"])).expanduser()
        include_source_updated: bool = bool(options["include_source_updated"])
        missing_marker: str = str(options["missing_marker"])
        only_missing: bool = bool(options["only_missing"])
        try:
            stats = export_locale_csv(
                locale_code=locale_code,
                out_dir=out_dir,
                include_source_updated=include_source_updated,
                missing_marker=missing_marker,
                only_missing=only_missing,
            )
        except CommandError as exc:
            raise exc

        self.stdout.write(
            "\n".join(
                [
                    "Export summary:",
                    f"- total_string_units: {stats.total_string_units}",
                    f"- approved_count: {stats.approved_count}",
                    f"- missing_count: {stats.missing_count}",
                    f"- output_path: {stats.output_path}",
                ]
            )
        )
