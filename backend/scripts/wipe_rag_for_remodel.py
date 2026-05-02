from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
CHROMA_DIR = DATA_DIR / "chroma"
CANVAS_UPLOADS = DATA_DIR / "canvas_rag_uploads"
RAG_UPLOADS = DATA_DIR / "rag_uploads"


def _human_size(path: Path) -> str:
    if not path.exists():
        return "missing"
    if path.is_file():
        return f"{path.stat().st_size / 1024:.1f} KB"
    total = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return f"{total / (1024 * 1024):.1f} MB"


def collect_chroma_targets() -> list[Path]:
    if not CHROMA_DIR.exists():
        return []
    return [p for p in CHROMA_DIR.iterdir() if p.is_dir()]


def collect_registry_files() -> list[Path]:
    out: list[Path] = []
    for root in (CANVAS_UPLOADS, RAG_UPLOADS):
        if not root.exists():
            continue
        out.extend(root.rglob(".indexed_files.json"))
        out.extend(root.rglob(".md5_registry.json"))
    if CHROMA_DIR.exists():
        out.extend(CHROMA_DIR.rglob("collection_registry.json"))
    return out


def wipe_filesystem(apply: bool) -> None:
    print("== Filesystem ==")
    for d in collect_chroma_targets():
        print(f"  [chroma] {d}  ({_human_size(d)})")
        if apply:
            shutil.rmtree(d, ignore_errors=True)
    for f in collect_registry_files():
        print(f"  [registry] {f}  ({_human_size(f)})")
        if apply:
            try:
                f.unlink()
            except OSError as exc:
                print(f"    skip ({exc})")


def wipe_database(apply: bool) -> None:
    print("== Database ==")
    # Imported lazily so dry-run works without a live DB.
    from backend.database.base import SessionLocal
    from sqlalchemy import text

    targets = [
        # Order matters: child tables first (FK ON DELETE CASCADE handles most,
        # but being explicit keeps the script readable).
        "rag_document_topics",
        "rag_collections",
        "canvas_course_domain_docs",
    ]

    with SessionLocal() as db:
        for table in targets:
            try:
                count = db.execute(
                    text(f"SELECT COUNT(*) FROM {table}")
                ).scalar()
            except Exception as exc:
                print(f"  [{table}] inspect failed: {exc}")
                continue
            print(f"  [{table}] rows={count}")
            if apply and count:
                db.execute(text(f"DELETE FROM {table}"))
        if apply:
            db.commit()
            print("  committed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete. Without this flag the script only prints a plan.",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Skip the Postgres DELETE step (use when DB is offline).",
    )
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== Phase-2 RAG wipe ({mode}) ===")
    print(f"Project root: {PROJECT_ROOT}")

    wipe_filesystem(args.apply)
    if not args.skip_db:
        wipe_database(args.apply)
    else:
        print("== Database ==\n  skipped (--skip-db)")

    if not args.apply:
        print("\nDry-run complete. Re-run with --apply to actually delete.")
    else:
        print("\nDone. Restart workers and re-trigger indexing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
