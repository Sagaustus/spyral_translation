"""
Semantic similarity scorer using sentence-transformers + XLM-R.

Used in the pipeline to compare the English source string against the
back-translated English string.  A low score indicates semantic drift —
the machine translation likely changed the meaning.

Install: pip install sentence-transformers
The ``paraphrase-multilingual-mpnet-base-v2`` model (~420 MB) is downloaded
once to the HuggingFace cache on first use.

Usage
-----
    from l10n.services.scorer import SimilarityScorer
    scorer = SimilarityScorer()
    score = scorer.score("Save document", "Save document")   # → ~1.0
    score = scorer.score("Save document", "Close window")    # → ~0.3
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "paraphrase-multilingual-mpnet-base-v2"


class SimilarityScorer:
    """Lazily-loaded cross-lingual sentence similarity scorer.

    The underlying model is loaded once on first call to :meth:`score` and
    then reused for the lifetime of the object.
    """

    def __init__(self, model_name: str | None = None) -> None:
        from django.conf import settings

        self._model_name: str = (
            model_name
            or getattr(settings, "SIMILARITY_MODEL", None)
            or _DEFAULT_MODEL
        )
        self._model: object | None = None

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is not installed. "
                "Run: pip install sentence-transformers"
            ) from exc

        logger.info(
            "Loading similarity model %s (first call may download ~420 MB)…",
            self._model_name,
        )
        self._model = SentenceTransformer(self._model_name)
        logger.info("Similarity model loaded.")

    def score(self, text_a: str, text_b: str) -> float:
        """Return cosine similarity in [0.0, 1.0] between *text_a* and *text_b*.

        Returns ``0.0`` if either string is empty.
        """
        a = (text_a or "").strip()
        b = (text_b or "").strip()
        if not a or not b:
            return 0.0

        self._load()
        assert self._model is not None

        from sentence_transformers import SentenceTransformer, util  # type: ignore[import]
        assert isinstance(self._model, SentenceTransformer)

        embeddings = self._model.encode([a, b], convert_to_tensor=True, normalize_embeddings=True)
        cosine = float(util.cos_sim(embeddings[0], embeddings[1]).item())
        # Clamp to [0, 1] — cosine can be very slightly outside due to float precision.
        return max(0.0, min(1.0, cosine))


# Module-level singleton — reused across pipeline iterations in the same process.
_scorer: SimilarityScorer | None = None


def get_scorer() -> SimilarityScorer:
    global _scorer
    if _scorer is None:
        _scorer = SimilarityScorer()
    return _scorer
