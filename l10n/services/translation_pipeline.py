from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterable

from django.core.management.base import CommandError

from .qa import compute_qa_flags


PH_TOKEN_PREFIX = "@@PH"
PH_TOKEN_SUFFIX = "@@"

TAG_TOKEN_PREFIX = "@@TAG"
TAG_TOKEN_SUFFIX = "@@"


def _safe_token(prefix: str, index: int, suffix: str) -> str:
    return f"{prefix}{index}{suffix}"


@dataclass(frozen=True)
class ProtectedText:
    text: str
    mapping: dict[str, str]


def protect_placeholders_and_tags(text: str) -> ProtectedText:
    """Replace placeholders and a small set of HTML tags with stable tokens.

    This helps MT models preserve formatting.

    - Placeholders: %-style and {...} style (using l10n.services.qa heuristics).
    - Tags: limited, heuristic set (using l10n.services.qa heuristics).

    Returns ProtectedText with a token->original mapping.
    """

    from .qa import extract_html_tags, extract_placeholders

    raw = text or ""
    mapping: dict[str, str] = {}

    # Replace placeholders by descending length to avoid partial overlaps.
    placeholders = sorted(extract_placeholders(raw), key=len, reverse=True)
    protected = raw
    for i, ph in enumerate(placeholders):
        token = _safe_token(PH_TOKEN_PREFIX, i, PH_TOKEN_SUFFIX)
        mapping[token] = ph
        protected = protected.replace(ph, token)

    # Replace actual tag *instances* (not just counts).
    # Keep this scoped: tags that commonly appear in Voyant UI strings.
    tag_names = "b|i|strong|em|span|a"
    tag_pattern = re.compile(rf"<\s*/?\s*(?:{tag_names})\b[^>]*>", re.IGNORECASE)

    tag_matches = list(tag_pattern.finditer(protected))
    if tag_matches:
        # Replace from end to start so indices remain valid.
        for i, match in enumerate(reversed(tag_matches)):
            token = _safe_token(TAG_TOKEN_PREFIX, i, TAG_TOKEN_SUFFIX)
            original = match.group(0)
            mapping[token] = original
            start, end = match.span()
            protected = protected[:start] + token + protected[end:]

    # Sanity check: counts should match after protection.
    src_flags = compute_qa_flags(source=raw, target=protected)
    # Only allow flags that are expected due to tokenization (extra placeholders/tags).
    # If we somehow lost braces, etc, fail loudly.
    unexpected = [f for f in src_flags if f.get("code") in {"unbalanced_braces"}]
    if unexpected:
        raise CommandError(f"Failed to protect text safely: {unexpected}")

    return ProtectedText(text=protected, mapping=mapping)


def unprotect(text: str, mapping: dict[str, str]) -> str:
    restored = text or ""
    # Restore longer tokens first.
    for token in sorted(mapping.keys(), key=len, reverse=True):
        restored = restored.replace(token, mapping[token])
    return restored


@dataclass(frozen=True)
class SimilarityResult:
    score: float


class SimilarityScorer:
    """XLM-R based semantic similarity scorer (via sentence-transformers)."""

    def __init__(self, model_id: str | None = None):
        self.model_id = model_id or os.environ.get(
            "XLMR_SIM_MODEL_ID", "sentence-transformers/paraphrase-xlm-r-multilingual-v1"
        )
        self._model = None

    def _load(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:  # pragma: no cover
            raise CommandError(
                "Missing ML dependencies. Install with: pip install -r requirements-ml.txt"
            ) from exc

        device = "cuda" if _torch_cuda_available() else "cpu"
        self._model = SentenceTransformer(self.model_id, device=device)

    def score(self, *, source_en: str, backtranslated_en: str) -> SimilarityResult:
        self._load()
        assert self._model is not None
        import numpy as np

        emb = self._model.encode([source_en, backtranslated_en], normalize_embeddings=True)
        a = np.asarray(emb[0], dtype=float)
        b = np.asarray(emb[1], dtype=float)
        return SimilarityResult(score=float((a * b).sum()))


def _torch_cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


class NLLBTranslator:
    """Local NLLB-200 translator using Hugging Face Transformers.

    Uses GPU automatically when available.
    """

    def __init__(
        self,
        model_id: str | None = None,
        *,
        source_lang: str,
        target_lang: str,
    ):
        self.model_id = model_id or os.environ.get("NLLB_MODEL_ID", "facebook/nllb-200-distilled-600M")
        self.source_lang = source_lang
        self.target_lang = target_lang
        self._tokenizer = None
        self._model = None

    def _load(self):
        if self._model is not None and self._tokenizer is not None:
            return

        hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
        if hf_token:
            try:
                from huggingface_hub import login

                login(token=hf_token, add_to_git_credential=False)
            except Exception:
                # Non-fatal; model downloads may still work.
                pass

        try:
            import torch
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        except Exception as exc:  # pragma: no cover
            raise CommandError(
                "Missing ML dependencies. Install with: pip install -r requirements-ml.txt"
            ) from exc

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if device == "cuda" else torch.float32

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_id)

        # device_map="auto" uses accelerate (if installed) and tends to do the right thing on GPU.
        # Fall back cleanly if unavailable.
        try:
            self._model = AutoModelForSeq2SeqLM.from_pretrained(
                self.model_id,
                torch_dtype=dtype,
                device_map="auto" if device == "cuda" else None,
            )
        except TypeError:
            self._model = AutoModelForSeq2SeqLM.from_pretrained(self.model_id, torch_dtype=dtype)
            self._model.to(device)

        self._model.eval()

    def translate(self, texts: Iterable[str], *, max_new_tokens: int = 256) -> list[str]:
        self._load()
        assert self._tokenizer is not None and self._model is not None

        import torch

        tokenizer = self._tokenizer
        model = self._model

        # NLLB uses tokenizer language codes like "eng_Latn", "yor_Latn".
        tokenizer.src_lang = self.source_lang

        inputs = tokenizer(list(texts), return_tensors="pt", padding=True, truncation=True)

        # If model is sharded with device_map, inputs need to be on model device.
        # This works for single-device setups; for multi-device, accelerate handles it.
        device = next(model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items()}

        forced_bos_token_id = tokenizer.convert_tokens_to_ids(self.target_lang)

        with torch.no_grad():
            generated = model.generate(
                **inputs,
                forced_bos_token_id=forced_bos_token_id,
                max_new_tokens=max_new_tokens,
            )

        out = tokenizer.batch_decode(generated, skip_special_tokens=True)
        return [s.strip() for s in out]


class AfroLinguMTTranslator:
    """Optional translator for AfroLingu-MT (or any HF seq2seq MT model you have access to)."""

    def __init__(self, model_id: str | None = None):
        self.model_id = model_id or os.environ.get("AFROLINGU_MT_MODEL_ID")
        self._pipeline = None

    def enabled(self) -> bool:
        return bool((self.model_id or "").strip())

    def _load(self):
        if self._pipeline is not None:
            return
        if not self.enabled():
            raise CommandError("AFROLINGU_MT_MODEL_ID is not set.")

        try:
            import torch
            from transformers import pipeline
        except Exception as exc:  # pragma: no cover
            raise CommandError(
                "Missing ML dependencies. Install with: pip install -r requirements-ml.txt"
            ) from exc

        device = 0 if torch.cuda.is_available() else -1
        self._pipeline = pipeline("translation", model=self.model_id, device=device)

    def translate(self, texts: Iterable[str]) -> list[str]:
        self._load()
        assert self._pipeline is not None
        outputs = self._pipeline(list(texts))
        # HF translation pipeline returns list[{'translation_text': ...}]
        return [o["translation_text"].strip() for o in outputs]


class OpenAITranslator:
    """Optional translator via OpenAI API (requires OPENAI_API_KEY)."""

    def __init__(self, model: str = "gpt-4.1-mini"):
        self.model = model

    def enabled(self) -> bool:
        return bool((os.environ.get("OPENAI_API_KEY") or "").strip())

    def translate(self, *, source_en: str, target_language_name: str, system_hint: str | None = None) -> str:
        if not self.enabled():
            raise CommandError("OPENAI_API_KEY is not set.")

        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover
            raise CommandError(
                "Missing ML dependencies. Install with: pip install -r requirements-ml.txt"
            ) from exc

        client = OpenAI()

        system = (
            system_hint
            or "You are a careful software localization translator. Preserve placeholders and HTML tags verbatim."
        )

        resp = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": f"Translate into {target_language_name}:\n\n{source_en}",
                },
            ],
            temperature=0.2,
        )

        return (resp.choices[0].message.content or "").strip()


def load_afrolingu_mt_dataset(*, split: str = "test", streaming: bool = True):
    """Load the gated AfroLingu-MT benchmark dataset from Hugging Face.

    This dataset requires accepting access conditions on Hugging Face.
    If you get a 401/403, log into HF, accept the dataset terms, and set HF_TOKEN.
    """

    dataset_id = os.environ.get("AFROLINGU_MT_DATASET_ID", "UBC-NLP/AfroLingu-MT")

    try:
        from datasets import load_dataset
    except Exception as exc:  # pragma: no cover
        raise CommandError(
            "Missing ML dependencies. Install with: pip install -r requirements-ml.txt"
        ) from exc

    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN")

    try:
        return load_dataset(dataset_id, split=split, streaming=streaming, token=hf_token)
    except TypeError:
        # Older datasets versions use use_auth_token.
        return load_dataset(
            dataset_id,
            split=split,
            streaming=streaming,
            use_auth_token=hf_token,
        )


def afrolingu_iter_pairs(
    *,
    split: str,
    src_code: str,
    tgt_code: str,
    limit: int | None = None,
) -> list[tuple[str, str]]:
    """Extract (src_text, tgt_text) examples for a language pair.

    The dataset schema is: langcode, instruction, input, output.
    We filter heuristically because langcode formatting varies.
    """

    ds = load_afrolingu_mt_dataset(split=split, streaming=True)

    src_code = (src_code or "").strip().lower()
    tgt_code = (tgt_code or "").strip().lower()

    def _match_langcode(langcode: str) -> bool:
        lc = (langcode or "").lower()
        # Common separators: -, _, /, whitespace.
        sep = r"[-_/\s]"
        return bool(
            re.search(rf"(?:^|{sep}){re.escape(src_code)}(?:$|{sep})", lc)
            and re.search(rf"(?:^|{sep}){re.escape(tgt_code)}(?:$|{sep})", lc)
        )

    pairs: list[tuple[str, str]] = []
    for row in ds:
        langcode = str(row.get("langcode", ""))
        if not _match_langcode(langcode):
            continue

        src = (row.get("input") or "").strip()
        tgt = (row.get("output") or "").strip()
        if not src or not tgt:
            continue

        pairs.append((src, tgt))
        if limit is not None and len(pairs) >= limit:
            break

    return pairs
