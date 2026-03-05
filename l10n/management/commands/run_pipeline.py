"""
management command: run_pipeline

Runs the full AI-assisted translation pipeline for one locale:

  1. For each StringUnit that lacks an approved translation in the target locale,
     create (or reuse) a Translation record.
  2. Protect ICU / HTML placeholders with numbered sentinels.
  3. Translate the protected source text → machine draft (NLLB / OpenAI / Ollama).
  4. Back-translate the draft → English (always uses NLLB for consistency).
  5. Compute XLM-R cosine similarity between source and back-translation.
  6. Add a QA flag if similarity < threshold.
  7. Run the existing QA checks (placeholders, HTML tags).
  8. Save the Translation record with status=MACHINE_DRAFT, provenance=MT or LLM.

Usage examples
--------------
  # Translate all untranslated Yoruba strings using NLLB-200:
  python manage.py run_pipeline --locale yo --engine nllb

  # Translate first 50 strings, dry-run (no DB writes):
  python manage.py run_pipeline --locale yo --engine nllb --limit 50 --dry-run

  # Re-translate strings that already have a draft (overwrite):
  python manage.py run_pipeline --locale yo --engine openai --force

  # Skip similarity scoring (faster, useful when sentence-transformers is unavailable):
  python manage.py run_pipeline --locale yo --engine nllb --no-score
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from l10n.models import Locale, StringUnit, Translation
from l10n.services.placeholder import protect, restore
from l10n.services.qa import compute_qa_flags
from l10n.services.translator import (
    PipelineConfigError,
    TranslationEngine,
    get_engine,
    locale_to_nllb,
)

logger = logging.getLogger(__name__)

SRC_NLLB = "eng_Latn"  # English → always the source language


@dataclass
class PipelineStats:
    total: int = 0
    skipped_approved: int = 0
    skipped_has_draft: int = 0
    translated: int = 0
    back_translated: int = 0
    scored: int = 0
    low_similarity: int = 0
    errors: int = 0
    error_ids: list[int] = field(default_factory=list)


def _provenance_for_engine(engine_name: str) -> str:
    name = engine_name.lower()
    if "openai" in name or "ollama" in name or "gpt" in name or "llama" in name:
        return Translation.TranslationProvenance.LLM
    return Translation.TranslationProvenance.MT


class Command(BaseCommand):
    help = (
        "Run the AI translation pipeline for a target locale. "
        "Generates machine drafts, back-translations, and similarity scores."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--locale",
            required=True,
            help="Target locale code (e.g. yo, ha, sw). Must exist in the database.",
        )
        parser.add_argument(
            "--engine",
            default="nllb",
            choices=["nllb", "openai", "ollama"],
            help="Translation engine to use (default: nllb).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of strings to process in this run.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Parse and report what would happen but do not write to the database.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-translate strings that already have a machine_draft (overwrite).",
        )
        parser.add_argument(
            "--no-score",
            action="store_true",
            dest="no_score",
            help="Skip similarity scoring (faster; skips back-translation too).",
        )
        parser.add_argument(
            "--similarity-threshold",
            type=float,
            default=None,
            dest="similarity_threshold",
            help="Score below which a 'low_similarity' QA flag is added (default from settings).",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print per-string progress.",
        )

    def handle(self, *args, **options) -> None:
        locale_code: str = options["locale"].strip().lower()
        engine_name: str = options["engine"]
        limit: int | None = options.get("limit")
        dry_run: bool = bool(options["dry_run"])
        force: bool = bool(options["force"])
        no_score: bool = bool(options["no_score"])
        verbose: bool = bool(options["verbose"])

        from django.conf import settings

        similarity_threshold: float = options.get("similarity_threshold") or float(
            getattr(settings, "SIMILARITY_THRESHOLD", 0.75)
        )

        # ── Resolve locale ──────────────────────────────────────────────────
        try:
            locale = Locale.objects.get(code=locale_code)
        except Locale.DoesNotExist:
            raise CommandError(
                f"Locale '{locale_code}' not found. "
                f"Run: python manage.py seed_locales  or add it via Admin."
            )

        # ── Resolve NLLB language codes ─────────────────────────────────────
        try:
            tgt_nllb = locale_to_nllb(locale_code)
        except PipelineConfigError as exc:
            raise CommandError(str(exc))

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\nPipeline: {locale.name} ({locale_code})  "
                f"engine={engine_name}  "
                f"dry_run={dry_run}  "
                f"force={force}  "
                f"no_score={no_score}"
            )
        )

        # ── Load translation engine ─────────────────────────────────────────
        try:
            engine: TranslationEngine = get_engine(engine_name)
        except PipelineConfigError as exc:
            raise CommandError(str(exc))

        # ── Load back-translation engine (always NLLB) ──────────────────────
        from l10n.services.translator import NLLBEngine
        from django.conf import settings as dj_settings

        nllb_model = getattr(dj_settings, "NLLB_MODEL_NAME", "facebook/nllb-200-distilled-600M")
        back_engine: NLLBEngine | None = None
        if not no_score:
            back_engine = NLLBEngine(model_name=nllb_model)

        # ── Load scorer ─────────────────────────────────────────────────────
        scorer = None
        if not no_score:
            from l10n.services.scorer import get_scorer
            scorer = get_scorer()

        # ── Fetch strings to process ────────────────────────────────────────
        # Preload existing Translation records for this locale.
        existing: dict[int, Translation] = {
            tr.string_unit_id: tr
            for tr in Translation.objects.filter(locale=locale).select_related("string_unit")
        }

        string_units = (
            StringUnit.objects.all()
            .order_by("location", "message_id")
            .only("id", "location", "message_id", "source_text", "source_hash")
        )

        stats = PipelineStats()

        for su in string_units.iterator():
            if limit is not None and stats.translated >= limit:
                break

            stats.total += 1
            tr = existing.get(su.id)

            # ── Skip approved ───────────────────────────────────────────────
            if tr and tr.status == Translation.TranslationStatus.APPROVED:
                stats.skipped_approved += 1
                if verbose:
                    self.stdout.write(f"  [skip-approved] {su}")
                continue

            # ── Skip if draft exists and not forcing ────────────────────────
            if tr and (tr.machine_draft or "").strip() and not force:
                stats.skipped_has_draft += 1
                if verbose:
                    self.stdout.write(f"  [skip-has-draft] {su}")
                continue

            source_text = (su.source_text or "").strip()
            if not source_text:
                if verbose:
                    self.stdout.write(f"  [skip-empty-source] {su}")
                continue

            try:
                # 1. Protect placeholders
                protected_src, restore_map = protect(source_text)

                # 2. Translate → machine draft
                raw_draft = engine.translate(protected_src, SRC_NLLB, tgt_nllb)
                machine_draft = restore(raw_draft, restore_map)
                stats.translated += 1

                if verbose:
                    self.stdout.write(f"  [translated] {su}")
                    self.stdout.write(f"    src:   {source_text[:80]}")
                    self.stdout.write(f"    draft: {machine_draft[:80]}")

                # 3. Back-translate draft → English
                back_text: str | None = None
                sim_score: float | None = None

                if back_engine is not None:
                    protected_draft, restore_map_back = protect(machine_draft)
                    raw_back = back_engine.translate(protected_draft, tgt_nllb, SRC_NLLB)
                    back_text = restore(raw_back, restore_map_back)
                    stats.back_translated += 1

                    if verbose:
                        self.stdout.write(f"    back:  {back_text[:80]}")

                # 4. Similarity score
                if scorer is not None and back_text:
                    sim_score = scorer.score(source_text, back_text)
                    stats.scored += 1

                    if verbose:
                        self.stdout.write(f"    score: {sim_score:.3f}")

                # 5. QA flags
                qa_flags = compute_qa_flags(source=source_text, target=machine_draft)

                if sim_score is not None and sim_score < similarity_threshold:
                    qa_flags.append(
                        {
                            "code": "low_similarity",
                            "message": (
                                f"Back-translation similarity {sim_score:.3f} is below "
                                f"threshold {similarity_threshold:.2f}. "
                                "The translation may have drifted semantically."
                            ),
                            "details": {
                                "score": round(sim_score, 4),
                                "threshold": similarity_threshold,
                                "back_translation": back_text,
                            },
                        }
                    )
                    stats.low_similarity += 1

                # 6. Determine status
                new_status = (
                    Translation.TranslationStatus.FLAGGED
                    if qa_flags
                    else Translation.TranslationStatus.MACHINE_DRAFT
                )

                if not dry_run:
                    with transaction.atomic():
                        if tr is None:
                            tr = Translation(
                                string_unit=su,
                                locale=locale,
                            )

                        tr.machine_draft = machine_draft
                        tr.back_translation = back_text
                        tr.similarity_score = sim_score
                        tr.engine = engine.name
                        tr.qa_flags = qa_flags
                        tr.status = new_status
                        tr.provenance = _provenance_for_engine(engine.name)
                        tr.source_hash_at_last_update = su.source_hash
                        # Override auto qa_flags computation in Translation.save()
                        # by pre-setting qa_flags and bypassing via update_fields
                        tr.save(
                            update_fields=[
                                "machine_draft",
                                "back_translation",
                                "similarity_score",
                                "engine",
                                "qa_flags",
                                "status",
                                "provenance",
                                "source_hash_at_last_update",
                            ]
                            if tr.pk
                            else None
                        )
                        existing[su.id] = tr

            except PipelineConfigError:
                raise  # Engine misconfiguration — abort the whole run
            except Exception as exc:  # noqa: BLE001
                stats.errors += 1
                stats.error_ids.append(su.id)
                logger.warning("Error processing StringUnit %d (%s): %s", su.id, su, exc)
                self.stderr.write(
                    self.style.WARNING(f"  [error] StringUnit {su.id} — {exc}")
                )

        # ── Summary ─────────────────────────────────────────────────────────
        self.stdout.write("\n" + self.style.SUCCESS("Pipeline complete."))
        self.stdout.write(f"  total strings seen:      {stats.total}")
        self.stdout.write(f"  skipped (approved):      {stats.skipped_approved}")
        self.stdout.write(f"  skipped (has draft):     {stats.skipped_has_draft}")
        self.stdout.write(f"  translated:              {stats.translated}")
        self.stdout.write(f"  back-translated:         {stats.back_translated}")
        self.stdout.write(f"  scored:                  {stats.scored}")
        self.stdout.write(f"  low-similarity flagged:  {stats.low_similarity}")
        self.stdout.write(f"  errors:                  {stats.errors}")

        if dry_run:
            self.stdout.write(self.style.WARNING("\n  [dry-run] No changes written to database."))
