"""
Lightweight benchmark / instrumentation helpers for the embedding & RAG path.

Goal: emit structured ``BENCH`` log lines that are trivial to grep and to
post-process when comparing the current embedding model (BAAI/bge-m3) against
candidate replacements. No external service, no metrics backend — just stdlib
logging plus optional ``psutil`` for RSS sampling.

Log format (single line per event)::

    BENCH | event=<name> | k1=v1 | k2=v2 | ms=<float> | rss_mb=<float> | pid=<int>

Usage::

    from .bench import bench_stage, bench_emit

    with bench_stage("pdf_load", file=filename):
        documents = load_pdf_documents(file_path)

    bench_emit("embedding_model_loaded", model=name, device=device)

The module is intentionally side-effect-free at import time aside from
attaching a logger handler-free child logger; psutil is optional and
gracefully degrades when not installed.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

# Route through the project's logger factory so BENCH lines land in a
# dedicated daily file (logs/bench_YYYYMMDD.log) instead of being dropped
# by the no-handler root logger. Falls back to a basic stdout logger when
# the backend logger module isn't importable (e.g. in isolated tests).
try:
    from backend.core.logger import setup_logger  # type: ignore
    logger = setup_logger(
        "bench",
        f"bench_{__import__('datetime').datetime.now().strftime('%Y%m%d')}.log",
        console_level=logging.WARNING,  # keep console quiet, file gets everything
    )
except Exception:  # pragma: no cover
    logger = logging.getLogger("backend.bench")
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(h)
    logger.setLevel(logging.INFO)

try:  # psutil is optional — instrumentation must never break the app.
    import psutil  # type: ignore
    _PROC = psutil.Process(os.getpid())
except Exception:  # pragma: no cover - environment without psutil
    psutil = None  # type: ignore
    _PROC = None


def rss_mb() -> Optional[float]:
    """Return current process RSS in MB, or ``None`` if psutil is missing."""
    if _PROC is None:
        return None
    try:
        return _PROC.memory_info().rss / (1024.0 * 1024.0)
    except Exception:
        return None


def _format_fields(fields: dict) -> str:
    parts = []
    for key, value in fields.items():
        if isinstance(value, float):
            parts.append(f"{key}={value:.3f}")
        else:
            parts.append(f"{key}={value}")
    return " | ".join(parts)


def bench_emit(event: str, **fields: Any) -> None:
    """Emit a single structured BENCH log line."""
    rss = rss_mb()
    if rss is not None and "rss_mb" not in fields:
        fields["rss_mb"] = round(rss, 1)
    fields["pid"] = os.getpid()
    logger.info("BENCH | event=%s | %s", event, _format_fields(fields))


@contextmanager
def bench_stage(event: str, **fields: Any) -> Iterator[dict]:
    """
    Context manager that times a block and emits a BENCH line on exit.

    Yields a mutable dict; callers may add fields inside the block (e.g. the
    real chunk count after splitting). Final emitted line includes ``ms`` and,
    when psutil is available, ``rss_delta_mb``.
    """
    extra: dict = {}
    t0 = time.perf_counter()
    rss0 = rss_mb()
    try:
        yield extra
    finally:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        rss1 = rss_mb()
        merged = dict(fields)
        merged.update(extra)
        merged["ms"] = round(dt_ms, 2)
        if rss0 is not None and rss1 is not None:
            merged["rss_delta_mb"] = round(rss1 - rss0, 1)
        bench_emit(event, **merged)
