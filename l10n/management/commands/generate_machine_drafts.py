from __future__ import annotations

import math
import os
from dataclasses import dataclass

from django.core.management.base import BaseCommand
from django.db import transaction

from l10n.models import Locale, StringUnit, Translation
from l10n.services.translation_pipeline import (
    NLLBTranslator,
    SimilarityScorer,
    protect_placeholders_and_tags,
    unprotect,
)
from l10n.services.qa import compute_qa_flags


@dataclass
class Counts:
    processed: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0


class Command(BaseCommand):
    help = (
        "Generate machine_draft translations for a locale using local NLLB-200 (GPU if available). "
        "Optionally computes back-translation similarity using an XLM-R scorer."
    )

    def add_arguments(self, parser):
        parser.add_argument("--locale", default="yo", help="Locale.code to generate drafts for (default yo)")
        parser.add_argument(
            "--limit",
            type=int,
            default=200,
            help="Max number of StringUnits to process (default 200).",
        )
        parser.add_argument(
            "--only-missing",
            action="store_true",
            dest="only_missing",
            help="Only generate drafts where approved_text is missing.",
        )
        parser.add_argument(
            "--no-similarity",
            action="store_true",
            dest="no_similarity",
            help="Skip back-translation + similarity scoring.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Compute drafts but do not write to the DB.",
        )

    def handle(self, *args, **options):
        locale_code: str = str(options["locale"]).strip()
        limit: int = int(options["limit"])
        only_missing: bool = bool(options["only_missing"])
        no_similarity: bool = bool(options["no_similarity"])
        dry_run: bool = bool(options["dry_run"])

        if limit < 0:
            raise ValueError("--limit must be >= 0")

        locale, _ = Locale.objects.get_or_create(
            code=locale_code,
            defaults={"bcp47": locale_code, "name": locale_code.upper(), "enabled": True},
        )

        # NLLB language codes are different from Locale.code.
        # For Yoruba we use yor_Latn. Override via env if you need other scripts.
        if locale_code == "yo":
            src_lang = "eng_Latn"
            tgt_lang = "yor_Latn"
        else:
            # Best-effort mapping; user can extend this later.
            src_lang = "eng_Latn"
            tgt_lang = os.environ.get("NLLB_TARGET_LANG") or "yor_Latn"

        translator = NLLBTranslator(source_lang=src_lang, target_lang=tgt_lang)

        scorer = None if no_similarity else SimilarityScorer()
        backtranslator = None
        if scorer is not None:
            backtranslator = NLLBTranslator(source_lang=tgt_lang, target_lang=src_lang)

        qs = StringUnit.objects.all().order_by("location", "message_id")
        if limit:
            qs = qs[:limit]

        counts = Counts()

        with transaction.atomic():
            for su in qs:
                source_en = (su.source_text or "").strip()
                if not source_en:
                    counts.skipped += 1
                    continue

                tr, created = Translation.objects.get_or_create(
                    string_unit=su,
                    locale=locale,
                    defaults={
                        "status": Translation.TranslationStatus.MACHINE_DRAFT,
                        "provenance": Translation.TranslationProvenance.MT,
                        "machine_draft": "",
                    },
                )

                if only_missing and (tr.approved_text or "").strip():
                    counts.skipped += 1
                    continue

                protected = protect_placeholders_and_tags(source_en)
                draft_protected = translator.translate([protected.text])[0]
                draft = unprotect(draft_protected, protected.mapping).strip()

                # Ensure draft is QA-safe; if not, keep it but flag by status.
                flags = tr.qa_flags or []
                new_flags = [f for f in flags if f.get("code") != "mt_pipeline_issue"]

                qa_flags = compute_qa_flags(source=source_en, target=draft)
                if qa_flags:
                    new_flags.append(
                        {
                            "code": "mt_pipeline_issue",
                            "message": "MT draft triggered QA flags; review required.",
                            "details": {"qa_flags": qa_flags},
                        }
                    )

                sim_score = None
                if scorer is not None and backtranslator is not None:
                    back = backtranslator.translate([protect_placeholders_and_tags(draft).text])[0]
                    sim_score = scorer.score(source_en=source_en, backtranslated_en=back).score

                tr.machine_draft = draft
                tr.status = Translation.TranslationStatus.MACHINE_DRAFT
                tr.provenance = Translation.TranslationProvenance.MT
                tr.qa_flags = new_flags

                if created:
                    counts.created += 1
                else:
                    counts.updated += 1

                counts.processed += 1

                if sim_score is not None and not math.isnan(sim_score):
                    self.stdout.write(
                        f"[{locale_code}] {su.location}::{su.message_id} similarity={sim_score:.3f}"
                    )

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write("Machine draft summary:")
        self.stdout.write(f"- processed: {counts.processed}")
        self.stdout.write(f"- created: {counts.created}")
        self.stdout.write(f"- updated: {counts.updated}")
        self.stdout.write(f"- skipped: {counts.skipped}")
        if dry_run:
            self.stdout.write("(dry-run: no changes were written)")
