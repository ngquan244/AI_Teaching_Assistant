"""
Language utilities for the document RAG layer.

Provides:
- ``detect_language(docs)``: best-effort language label for a list of
  langchain Documents — returns ``"vi"``, ``"en"``, ``"mixed"`` or ``None``.
- ``detect_topic_language(text)``: same logic for a short query/topic string.
- ``translate_topic(topic, target_lang, llm)``: cheap LLM-based translation
  of a short topic phrase, used by the cross-language retrieval fan-out.

Design notes
------------
* ``langdetect`` is imported lazily so importing this module never triggers
  a heavy dependency load (matches the project's lazy-import discipline,
  see ``/memories/repo/lazy-import-architecture.md``).
* The detector is seeded for deterministic results (per langdetect docs).
* All functions are defensive — any failure returns ``None`` / falls back
  to the input string. Callers must treat language info as best-effort.
"""

from __future__ import annotations

import logging
from typing import Iterable, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.documents import Document

logger = logging.getLogger(__name__)


# Languages we explicitly bucket. Anything else falls into the closest of
# {"vi", "en"} or "mixed" if both appear.
_VI = "vi"
_EN = "en"
_MIXED = "mixed"

_DETECTOR_READY = False


def _ensure_detector() -> bool:
    """Lazily configure langdetect for deterministic output. Returns
    ``False`` if langdetect cannot be imported (graceful no-op)."""
    global _DETECTOR_READY
    if _DETECTOR_READY:
        return True
    try:
        from langdetect import DetectorFactory  # type: ignore
        DetectorFactory.seed = 0
        _DETECTOR_READY = True
        return True
    except Exception as exc:  # pragma: no cover - import-time failure
        logger.warning("langdetect unavailable, language detection disabled: %s", exc)
        return False


def _detect_one(text: str) -> Optional[str]:
    if not text or not text.strip():
        return None
    if not _ensure_detector():
        return None
    try:
        from langdetect import detect  # type: ignore
        code = detect(text)
    except Exception:
        return None
    if not code:
        return None
    code = code.lower()
    if code.startswith("vi"):
        return _VI
    # langdetect returns "en", "fr", "de", ... For V1 we only branch
    # vi vs everything-else, so collapse non-Vietnamese to "en".
    return _EN


def _bucket_to_label(buckets: Iterable[str]) -> Optional[str]:
    seen = {b for b in buckets if b}
    if not seen:
        return None
    if seen == {_VI}:
        return _VI
    if seen == {_EN}:
        return _EN
    return _MIXED


def detect_language(documents: "List[Document]") -> Optional[str]:
    """Best-effort dominant language across a list of chunks.

    Samples up to the first 5 chunks (fast, deterministic). Returns
    ``"vi" | "en" | "mixed" | None``.
    """
    if not documents:
        return None
    if not _ensure_detector():
        return None
    sampled = []
    for doc in documents[:5]:
        text = getattr(doc, "page_content", "") or ""
        text = text.strip()
        if len(text) >= 40:  # langdetect is unreliable on tiny strings
            sampled.append(text[:1500])
    if not sampled:
        # Fall back to whatever we have, even if short
        sampled = [
            (getattr(doc, "page_content", "") or "").strip()
            for doc in documents[:3]
        ]
        sampled = [t for t in sampled if t]
    if not sampled:
        return None
    buckets = [_detect_one(t) for t in sampled]
    return _bucket_to_label(buckets)


def detect_topic_language(text: str) -> Optional[str]:
    """Detect the language of a short topic/query string.

    Returns ``"vi" | "en" | None`` (never ``"mixed"`` — a single short
    phrase is treated as a single language for fan-out decisions).
    """
    if not text or not text.strip():
        return None
    return _detect_one(text)


def translate_topic(
    topic: str,
    target_lang: str,
    llm,
) -> Optional[str]:
    """Translate a short topic phrase via the provided LLM.

    Falls back to ``None`` on any failure. Callers should cache the result
    per-request to avoid duplicate calls.
    """
    if not topic or not topic.strip():
        return None
    target_lang = (target_lang or "").lower()
    if target_lang == _VI:
        instruction = (
            "Translate the following short academic topic phrase to "
            "Vietnamese. Reply with ONLY the translated phrase, no quotes, "
            "no explanation."
        )
    elif target_lang == _EN:
        instruction = (
            "Translate the following short academic topic phrase to "
            "English. Reply with ONLY the translated phrase, no quotes, "
            "no explanation."
        )
    else:
        return None

    prompt = f"{instruction}\n\nPhrase: {topic.strip()}"
    try:
        msg = llm.invoke(prompt)
        text = msg.content if hasattr(msg, "content") else str(msg)
    except Exception as exc:
        logger.warning("translate_topic failed: %s", exc)
        return None
    text = (text or "").strip().strip('"').strip("'")
    if not text:
        return None
    # Strip trivial leading labels like "Translation:" the model may add.
    for prefix in ("Translation:", "translation:", "Câu dịch:", "Bản dịch:"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    return text or None
