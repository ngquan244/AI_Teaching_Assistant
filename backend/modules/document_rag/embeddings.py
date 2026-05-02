"""
Embedding model factory + wrappers.

Phase-2 changes
---------------
- Introduces ``build_embeddings(model_name, device, batch_size, normalize)`` so
  every initialisation site (``PerFileCollectionManager`` and
  ``ChromaVectorStore``) goes through the same code path.
- Adds ``E5PrefixedEmbeddings`` for the ``intfloat/multilingual-e5-*`` family,
  which **requires** "passage: " / "query: " prefixes on inputs. Skipping the
  prefixes silently degrades retrieval quality by ~10 %.
- Adds ``model_slug(model_name)`` so collection names can include model
  identity (avoids mixing 384-dim and 1024-dim vectors in the same store on
  future model swaps).
"""

from __future__ import annotations

import re
from typing import List

from langchain_core.embeddings import Embeddings
from langchain_huggingface import HuggingFaceEmbeddings


# ---------------------------------------------------------------------------
# Model identity helpers
# ---------------------------------------------------------------------------

# Hand-curated short slugs for the models we actually consider. Anything not
# listed gets a deterministic fallback derived from the model name, so the
# system still works with arbitrary HF model ids.
_KNOWN_SLUGS = {
    "BAAI/bge-m3": "bgem3",
    "intfloat/multilingual-e5-small": "e5s",
    "intfloat/multilingual-e5-base": "e5b",
    "intfloat/multilingual-e5-large": "e5l",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": "minilm",
}


def model_slug(model_name: str) -> str:
    """
    Return a short, filesystem/collection-safe identifier for ``model_name``.

    Stable across runs so a collection name encodes which model produced its
    vectors. Length is capped at 8 chars to leave room for the rest of the
    collection name within ChromaDB's 63-char limit.
    """
    if not model_name:
        return "unk"
    if model_name in _KNOWN_SLUGS:
        return _KNOWN_SLUGS[model_name]
    # Fallback: take the leaf, strip non-alnum, lowercase, truncate.
    leaf = model_name.split("/")[-1].lower()
    leaf = re.sub(r"[^a-z0-9]", "", leaf)
    return (leaf or "unk")[:8]


def is_e5_model(model_name: str) -> bool:
    """True for the intfloat/e5 family which requires input prefixes."""
    return "e5" in (model_name or "").lower()


# ---------------------------------------------------------------------------
# Prefix-aware wrapper
# ---------------------------------------------------------------------------

class E5PrefixedEmbeddings(Embeddings):
    """
    Wrap a ``HuggingFaceEmbeddings`` instance and prepend the E5-required
    ``"passage: "`` / ``"query: "`` prefixes before delegating.

    The underlying model still does the heavy lifting; this class only
    rewrites the input strings. It implements the LangChain ``Embeddings``
    protocol, so it is a drop-in for ``Chroma(embedding_function=...)`` and
    ``langchain`` retrievers without any other changes.
    """

    PASSAGE_PREFIX = "passage: "
    QUERY_PREFIX = "query: "

    def __init__(self, inner: HuggingFaceEmbeddings):
        self._inner = inner

    # The ``Embeddings`` ABC only requires these two methods.
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._inner.embed_documents(
            [f"{self.PASSAGE_PREFIX}{t}" for t in texts]
        )

    def embed_query(self, text: str) -> List[float]:
        return self._inner.embed_query(f"{self.QUERY_PREFIX}{text}")

    # Convenience pass-through: Chroma occasionally peeks at attributes
    # (e.g. ``model_name``) for diagnostics. Forward unknown reads to the
    # inner object so we don't break introspection.
    def __getattr__(self, item):  # pragma: no cover - trivial
        return getattr(self._inner, item)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_embeddings(
    model_name: str,
    device: str,
    batch_size: int,
    normalize: bool,
) -> Embeddings:
    """
    Construct the embedding object used everywhere in the RAG pipeline.

    Returns an ``Embeddings`` (LangChain protocol). For E5 models the result
    is an ``E5PrefixedEmbeddings`` wrapper; otherwise the bare
    ``HuggingFaceEmbeddings`` is returned.
    """
    inner = HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": device},
        encode_kwargs={
            "normalize_embeddings": normalize,
            "batch_size": batch_size,
        },
    )
    if is_e5_model(model_name):
        return E5PrefixedEmbeddings(inner)
    return inner
