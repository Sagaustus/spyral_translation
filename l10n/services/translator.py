"""
Translation engine adapters for the pipeline.

Each adapter implements the ``TranslationEngine`` protocol:

    translate(text, src_lang, tgt_lang) -> str

Language codes used here are NLLB-200 floret codes (e.g. ``yor_Latn``),
not BCP-47.  The ``NLLB_LANG`` mapping converts BCP-47 / locale.code values
to the right floret code before calling any engine.

Engines are instantiated lazily; import errors for optional dependencies
surface as ``PipelineConfigError`` with actionable messages.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# NLLB-200 floret language codes.
# Keys are either locale.code (as stored in Locale.code) or common BCP-47.
# Values are NLLB-200 floret codes accepted by the model tokeniser.
# ---------------------------------------------------------------------------
NLLB_LANG: dict[str, str] = {
    # African languages
    "yo": "yor_Latn",
    "ha": "hau_Latn",
    "ig": "ibo_Latn",
    "sw": "swh_Latn",
    "am": "amh_Ethi",
    "zu": "zul_Latn",
    "xh": "xho_Latn",
    "so": "som_Latn",
    "rw": "kin_Latn",
    "sn": "sna_Latn",
    "ti": "tir_Ethi",
    # European/Asian (Voyant already supports these, but useful for back-translation)
    "en": "eng_Latn",
    "fr": "fra_Latn",
    "de": "deu_Latn",
    "es": "spa_Latn",
    "pt": "por_Latn",
    "it": "ita_Latn",
    "ar": "arb_Arab",
    "hi": "hin_Deva",
    "zh-hans": "zho_Hans",
    "zh-hant": "zho_Hant",
    "cs": "ces_Latn",
    "ja": "jpn_Jpan",
}


class PipelineConfigError(RuntimeError):
    """Raised when an engine cannot be initialised due to missing config/deps."""


@runtime_checkable
class TranslationEngine(Protocol):
    @property
    def name(self) -> str: ...

    def translate(self, text: str, src_lang: str, tgt_lang: str) -> str: ...


# ---------------------------------------------------------------------------
# NLLB-200 engine (local, no API key required)
# ---------------------------------------------------------------------------

class NLLBEngine:
    """NLLB-200 via HuggingFace Transformers.

    The model (~1.2 GB for the 600M distilled variant) is downloaded once to
    the HuggingFace cache on first use.  Subsequent calls reuse the in-process
    pipeline object.

    Install: pip install transformers torch sentencepiece
    """

    def __init__(self, model_name: str = "facebook/nllb-200-distilled-600M") -> None:
        self._model_name = model_name
        self._tokenizer: object | None = None
        self._model: object | None = None

    @property
    def name(self) -> str:
        return self._model_name

    def _load(self) -> None:
        if self._tokenizer is not None and self._model is not None:
            return
        try:
            import os
            import torch  # type: ignore[import]
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer  # type: ignore[import]
        except ImportError as exc:
            raise PipelineConfigError(
                "Missing ML dependencies for NLLB. "
                "Run: pip install transformers torch sentencepiece"
            ) from exc

        # Optional: authenticate to Hugging Face Hub for gated models / higher rate limits.
        hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
        if hf_token:
            try:
                from huggingface_hub import login  # type: ignore[import]

                login(token=hf_token, add_to_git_credential=False)
            except Exception:
                pass

        logger.info("Loading NLLB-200 model %s (first call downloads ~1.2 GB)…", self._model_name)

        device = "cuda" if bool(torch.cuda.is_available()) else "cpu"
        dtype = torch.float16 if device == "cuda" else torch.float32

        tokenizer = AutoTokenizer.from_pretrained(self._model_name)

        # Prefer accelerate-style sharding on GPU when available.
        try:
            model = AutoModelForSeq2SeqLM.from_pretrained(
                self._model_name,
                torch_dtype=dtype,
                device_map="auto" if device == "cuda" else None,
            )
        except TypeError:
            model = AutoModelForSeq2SeqLM.from_pretrained(self._model_name, torch_dtype=dtype)
            model.to(device)

        model.eval()

        self._tokenizer = tokenizer
        self._model = model
        logger.info("NLLB-200 model loaded.")

    def translate(self, text: str, src_lang: str, tgt_lang: str) -> str:
        if not text.strip():
            return text
        self._load()
        assert self._tokenizer is not None and self._model is not None

        import torch  # type: ignore[import]

        tokenizer = self._tokenizer
        model = self._model

        # NLLB uses tokenizer language codes like "eng_Latn", "yor_Latn".
        tokenizer.src_lang = src_lang  # type: ignore[attr-defined]

        inputs = tokenizer([text], return_tensors="pt", padding=True, truncation=True)

        # If model is sharded with device_map, inputs need to be on model device.
        device = next(model.parameters()).device  # type: ignore[attr-defined]
        inputs = {k: v.to(device) for k, v in inputs.items()}

        forced_bos_token_id = tokenizer.convert_tokens_to_ids(tgt_lang)

        with torch.no_grad():
            generated = model.generate(
                **inputs,
                forced_bos_token_id=forced_bos_token_id,
                max_new_tokens=256,
            )

        out = tokenizer.batch_decode(generated, skip_special_tokens=True)
        return (out[0] or "").strip()


# ---------------------------------------------------------------------------
# OpenAI engine (optional)
# ---------------------------------------------------------------------------

class OpenAIEngine:
    """Translation via OpenAI Chat Completions.

    Install: pip install openai
    Set env vars: OPENAI_API_KEY, OPENAI_MODEL (default: gpt-4o-mini)
    """

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        if not api_key:
            raise PipelineConfigError(
                "OPENAI_API_KEY is not set. "
                "Add it to your .env file or environment."
            )
        self._api_key = api_key
        self._model = model
        self._client: object | None = None

    @property
    def name(self) -> str:
        return f"openai/{self._model}"

    def _load(self) -> None:
        if self._client is not None:
            return
        try:
            import openai  # type: ignore[import]
        except ImportError as exc:
            raise PipelineConfigError(
                "openai package is not installed. Run: pip install openai"
            ) from exc
        self._client = openai.OpenAI(api_key=self._api_key)

    def translate(self, text: str, src_lang: str, tgt_lang: str) -> str:
        if not text.strip():
            return text
        self._load()

        # Map NLLB floret code back to a human-readable name for the prompt.
        lang_name = _floret_to_name(tgt_lang)
        prompt = (
            f"Translate the following UI string from English to {lang_name}. "
            f"Preserve any placeholder tokens (e.g. {{0}}, %s) exactly as they appear. "
            f"Return ONLY the translation, no explanation.\n\n{text}"
        )
        import openai  # type: ignore[import]
        assert isinstance(self._client, openai.OpenAI)
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return (response.choices[0].message.content or "").strip()


# ---------------------------------------------------------------------------
# Ollama engine (local LLM server)
# ---------------------------------------------------------------------------

class OllamaEngine:
    """Translation via a local Ollama server.

    Install: pip install requests
    Set env vars: OLLAMA_BASE_URL (default: http://localhost:11434),
                  OLLAMA_MODEL (default: llama3)
    """

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3") -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    @property
    def name(self) -> str:
        return f"ollama/{self._model}"

    def translate(self, text: str, src_lang: str, tgt_lang: str) -> str:
        if not text.strip():
            return text
        try:
            import requests  # type: ignore[import]
        except ImportError as exc:
            raise PipelineConfigError(
                "requests is not installed. Run: pip install requests"
            ) from exc

        lang_name = _floret_to_name(tgt_lang)
        prompt = (
            f"Translate the following UI string from English to {lang_name}. "
            f"Preserve any placeholder tokens (e.g. {{0}}, %s) exactly. "
            f"Return ONLY the translation.\n\n{text}"
        )
        try:
            resp = requests.post(
                f"{self._base_url}/api/generate",
                json={"model": self._model, "prompt": prompt, "stream": False},
                timeout=120,
            )
            resp.raise_for_status()
            return (resp.json().get("response") or "").strip()
        except Exception as exc:
            raise PipelineConfigError(
                f"Ollama request failed ({self._base_url}): {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Reverse map: floret code → English language name (for LLM prompts)
_FLORET_NAMES: dict[str, str] = {
    "yor_Latn": "Yoruba",
    "hau_Latn": "Hausa",
    "ibo_Latn": "Igbo",
    "swh_Latn": "Swahili",
    "amh_Ethi": "Amharic",
    "zul_Latn": "isiZulu",
    "xho_Latn": "isiXhosa",
    "som_Latn": "Somali",
    "kin_Latn": "Kinyarwanda",
    "sna_Latn": "Shona",
    "tir_Ethi": "Tigrinya",
    "eng_Latn": "English",
    "fra_Latn": "French",
    "deu_Latn": "German",
    "spa_Latn": "Spanish",
    "por_Latn": "Portuguese",
    "ita_Latn": "Italian",
    "arb_Arab": "Arabic",
    "hin_Deva": "Hindi",
    "zho_Hans": "Chinese (Simplified)",
    "zho_Hant": "Chinese (Traditional)",
    "ces_Latn": "Czech",
    "jpn_Jpan": "Japanese",
}


def _floret_to_name(floret_code: str) -> str:
    return _FLORET_NAMES.get(floret_code, floret_code)


def locale_to_nllb(locale_code: str) -> str:
    """Convert a Locale.code (BCP-47-ish) to an NLLB-200 floret code.

    Raises PipelineConfigError if the locale is not in the mapping.
    """
    code = locale_code.lower().strip()
    if code not in NLLB_LANG:
        raise PipelineConfigError(
            f"No NLLB-200 language code known for locale '{locale_code}'. "
            f"Add it to NLLB_LANG in services/translator.py."
        )
    return NLLB_LANG[code]


def get_engine(engine_name: str) -> TranslationEngine:
    """Instantiate the requested translation engine from Django settings.

    engine_name choices: "nllb", "openai", "ollama"
    """
    from django.conf import settings

    name = (engine_name or "nllb").lower().strip()

    if name == "nllb":
        model = getattr(settings, "NLLB_MODEL_NAME", "facebook/nllb-200-distilled-600M")
        return NLLBEngine(model_name=model)

    if name == "openai":
        api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
        model = getattr(settings, "OPENAI_MODEL", "gpt-4o-mini")
        return OpenAIEngine(api_key=api_key, model=model)

    if name == "ollama":
        base_url = getattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434")
        model = getattr(settings, "OLLAMA_MODEL", "llama3")
        return OllamaEngine(base_url=base_url, model=model)

    raise PipelineConfigError(
        f"Unknown engine '{engine_name}'. Choose one of: nllb, openai, ollama."
    )
