from __future__ import annotations

from django.core.management.base import BaseCommand

from l10n.services.translation_pipeline import NLLBTranslator, afrolingu_iter_pairs


class Command(BaseCommand):
    help = (
        "Evaluate a translation engine against the AfroLingu-MT benchmark (HF gated dataset). "
        "This is useful for sanity-checking Yoruba MT quality on a GPU machine."
    )

    def add_arguments(self, parser):
        parser.add_argument("--src", default="eng", help="Source language code (default eng)")
        parser.add_argument("--tgt", default="yor", help="Target language code (default yor)")
        parser.add_argument(
            "--split",
            default="test",
            choices=["train", "validation", "test"],
            help="Dataset split to use (default test)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=200,
            help="Max number of examples to evaluate (default 200)",
        )
        parser.add_argument(
            "--engine",
            default="nllb",
            choices=["nllb"],
            help="Translation engine to evaluate (currently: nllb)",
        )

    def handle(self, *args, **options):
        src: str = str(options["src"]).strip().lower()
        tgt: str = str(options["tgt"]).strip().lower()
        split: str = str(options["split"]).strip()
        limit: int = int(options["limit"])
        engine: str = str(options["engine"]).strip().lower()

        if limit < 1:
            self.stdout.write("Nothing to do (limit < 1).")
            return

        # Map dataset ISO-ish codes to NLLB script codes.
        # For Yoruba and English this is straightforward.
        if src == "eng":
            nllb_src = "eng_Latn"
        else:
            nllb_src = "eng_Latn"

        if tgt == "yor":
            nllb_tgt = "yor_Latn"
        else:
            nllb_tgt = "yor_Latn"

        pairs = afrolingu_iter_pairs(split=split, src_code=src, tgt_code=tgt, limit=limit)
        if not pairs:
            self.stdout.write(
                "No examples found. If you hit an auth error, accept the dataset terms on HF and set HF_TOKEN."
            )
            return

        sources = [p[0] for p in pairs]
        references = [p[1] for p in pairs]

        if engine == "nllb":
            translator = NLLBTranslator(source_lang=nllb_src, target_lang=nllb_tgt)
            hypotheses = translator.translate(sources)
        else:
            raise ValueError(f"Unsupported engine: {engine}")

        try:
            import sacrebleu
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "sacrebleu not installed. Install optional deps: pip install -r requirements-ml.txt"
            ) from exc

        bleu = sacrebleu.corpus_bleu(hypotheses, [references])

        self.stdout.write("AfroLingu-MT evaluation:")
        self.stdout.write(f"- split: {split}")
        self.stdout.write(f"- pair: {src}->{tgt}")
        self.stdout.write(f"- engine: {engine}")
        self.stdout.write(f"- examples: {len(pairs)}")
        self.stdout.write(f"- BLEU: {bleu.score:.2f}")
