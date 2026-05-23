"""
V2 — Course-shared domain knowledge: eligibility & permissioning tests.

These are focused unit tests on the route handler bodies, exercising only
the V2 spec-binding rules:
  * Only Canvas-pipeline docs (source=CANVAS) can be marked.
  * A doc must belong to the target course.
  * Mixed payloads are rejected atomically (no partial inserts).
  * Feature flag off ⇒ 403 FEATURE_DISABLED.
  * Insufficient Canvas role ⇒ 403 INSUFFICIENT_ROLE.

The DB layer and Canvas API are mocked; we never spin up a TestClient.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest
from fastapi import HTTPException

from backend.routes import canvas_rag as routes
from backend.database.models.rag_document import RAGSourceType


# ─── Helpers ────────────────────────────────────────────────────────────

def _user(uid: str = "11111111-1111-1111-1111-111111111111"):
    return SimpleNamespace(id=uuid.UUID(uid))


def _row(file_hash: str, *, source=RAGSourceType.CANVAS, course_id=42):
    return SimpleNamespace(
        file_hash=file_hash,
        source=source,
        course_id=course_id,
        collection_name=f"canvas_{course_id}_{file_hash[:16]}",
        language="en",
    )


@contextmanager
def _mock_session():
    """Fake SessionLocal context manager."""
    db = MagicMock()
    db.commit = MagicMock()
    db.rollback = MagicMock()
    yield db


def _patch_common(
    *,
    feature_on: bool = True,
    canvas_check_ok: bool = True,
    canvas_check_role_ok: bool = True,
):
    """Patch the cross-cutting dependencies used by mark/unmark routes.

    Returns the patcher list — caller must enter as a contextmanager via
    ``with contextlib.ExitStack() as stk: ...``.
    """
    patches = []
    patches.append(patch.object(routes.settings, "ENABLE_COURSE_DOMAIN_DOCS", feature_on))
    patches.append(patch.object(routes, "SessionLocal", _mock_session))

    async def _fake_check(request, *, course_id=None, filename=None,
                          user_id=None, require_privileged_role=False):
        if not canvas_check_ok:
            raise HTTPException(status_code=403, detail="course access denied")
        if require_privileged_role and not canvas_check_role_ok:
            raise HTTPException(
                status_code=403,
                detail={"error": "INSUFFICIENT_ROLE", "actual_roles": ["student"]},
            )

    patches.append(patch.object(routes, "_check_canvas_permission", _fake_check))
    return patches


# ─── Eligibility — POST /domain-documents ──────────────────────────────

def test_mark_rejects_uploaded_doc_with_400_NOT_CANVAS_DOC():
    """Uploaded (source=DOCUMENT) hashes are NOT eligible — atomic 400."""
    body = routes.CourseDomainDocsMarkRequest(file_hashes=["aaaaaaaaaaaaaaaa"])
    upsert_called = MagicMock()

    with patch.object(
        routes.SyncRAGCollectionRepository, "get_by_hashes", return_value=[]
    ), patch.object(
        routes.SyncCanvasCourseDomainDocRepository, "upsert_many", upsert_called
    ):
        from contextlib import ExitStack
        with ExitStack() as stk:
            for p in _patch_common():
                stk.enter_context(p)

            with pytest.raises(HTTPException) as exc:
                asyncio.run(routes.mark_course_domain_documents(
                    course_id=42, body=body, http_request=MagicMock(), user=_user(),
                ))

    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "NOT_CANVAS_DOC"
    assert "aaaaaaaaaaaaaaaa" in exc.value.detail["ineligible_hashes"]
    upsert_called.assert_not_called()  # atomic — no insert


def test_mark_rejects_wrong_course_with_400_WRONG_COURSE():
    """Canvas doc indexed under course X cannot be marked under course Y."""
    body = routes.CourseDomainDocsMarkRequest(file_hashes=["bbbbbbbbbbbbbbbb"])
    upsert_called = MagicMock()

    rows = [_row("bbbbbbbbbbbbbbbb", course_id=999)]  # different course
    with patch.object(
        routes.SyncRAGCollectionRepository, "get_by_hashes", return_value=rows
    ), patch.object(
        routes.SyncCanvasCourseDomainDocRepository, "upsert_many", upsert_called
    ):
        from contextlib import ExitStack
        with ExitStack() as stk:
            for p in _patch_common():
                stk.enter_context(p)

            with pytest.raises(HTTPException) as exc:
                asyncio.run(routes.mark_course_domain_documents(
                    course_id=42, body=body, http_request=MagicMock(), user=_user(),
                ))

    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "WRONG_COURSE"
    assert "bbbbbbbbbbbbbbbb" in exc.value.detail["ineligible_hashes"]
    upsert_called.assert_not_called()


def test_mark_mixed_payload_is_atomic_no_partial_insert():
    """One valid + one invalid hash ⇒ entire request rejected, no rows inserted."""
    body = routes.CourseDomainDocsMarkRequest(
        file_hashes=["validhashvalidhash", "intruderintruder"],
    )
    upsert_called = MagicMock()

    # Only the valid hash returns a row — the intruder is unknown.
    rows = [_row("validhashvalidhash", course_id=42)]
    with patch.object(
        routes.SyncRAGCollectionRepository, "get_by_hashes", return_value=rows
    ), patch.object(
        routes.SyncCanvasCourseDomainDocRepository, "upsert_many", upsert_called
    ):
        from contextlib import ExitStack
        with ExitStack() as stk:
            for p in _patch_common():
                stk.enter_context(p)

            with pytest.raises(HTTPException) as exc:
                asyncio.run(routes.mark_course_domain_documents(
                    course_id=42, body=body, http_request=MagicMock(), user=_user(),
                ))

    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "NOT_CANVAS_DOC"
    assert "intruderintruder" in exc.value.detail["ineligible_hashes"]
    upsert_called.assert_not_called()  # atomic — valid hash NOT inserted either


def test_mark_happy_path_all_eligible_inserts_atomically():
    body = routes.CourseDomainDocsMarkRequest(
        file_hashes=["a" * 16, "b" * 16],
    )
    rows = [_row("a" * 16, course_id=42), _row("b" * 16, course_id=42)]
    with patch.object(
        routes.SyncRAGCollectionRepository, "get_by_hashes", return_value=rows
    ), patch.object(
        routes.SyncCanvasCourseDomainDocRepository, "upsert_many", return_value=2
    ) as upsert_called:
        from contextlib import ExitStack
        with ExitStack() as stk:
            for p in _patch_common():
                stk.enter_context(p)
            result = asyncio.run(routes.mark_course_domain_documents(
                course_id=42, body=body, http_request=MagicMock(), user=_user(),
            ))

    assert result["success"] is True
    assert result["marked_count"] == 2
    assert sorted(result["file_hashes"]) == ["a" * 16, "b" * 16]
    upsert_called.assert_called_once()


# ─── Feature flag ───────────────────────────────────────────────────────

def test_mark_returns_403_FEATURE_DISABLED_when_flag_off():
    body = routes.CourseDomainDocsMarkRequest(file_hashes=["a" * 16])

    from contextlib import ExitStack
    with ExitStack() as stk:
        for p in _patch_common(feature_on=False):
            stk.enter_context(p)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(routes.mark_course_domain_documents(
                course_id=42, body=body, http_request=MagicMock(), user=_user(),
            ))

    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "FEATURE_DISABLED"


def test_unmark_returns_403_FEATURE_DISABLED_when_flag_off():
    from contextlib import ExitStack
    with ExitStack() as stk:
        for p in _patch_common(feature_on=False):
            stk.enter_context(p)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(routes.unmark_course_domain_document(
                course_id=42, file_hash="x" * 16, http_request=MagicMock(), user=_user(),
            ))

    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "FEATURE_DISABLED"


# ─── Role gating ────────────────────────────────────────────────────────

def test_mark_returns_403_INSUFFICIENT_ROLE_for_student():
    body = routes.CourseDomainDocsMarkRequest(file_hashes=["a" * 16])
    from contextlib import ExitStack
    with ExitStack() as stk:
        for p in _patch_common(canvas_check_role_ok=False):
            stk.enter_context(p)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(routes.mark_course_domain_documents(
                course_id=42, body=body, http_request=MagicMock(), user=_user(),
            ))

    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "INSUFFICIENT_ROLE"


def test_unmark_returns_403_INSUFFICIENT_ROLE_for_student():
    from contextlib import ExitStack
    with ExitStack() as stk:
        for p in _patch_common(canvas_check_role_ok=False):
            stk.enter_context(p)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(routes.unmark_course_domain_document(
                course_id=42, file_hash="a" * 16, http_request=MagicMock(), user=_user(),
            ))

    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "INSUFFICIENT_ROLE"


# ─── Empty payload ──────────────────────────────────────────────────────

def test_mark_returns_400_EMPTY_PAYLOAD_when_hashes_missing():
    body = routes.CourseDomainDocsMarkRequest(file_hashes=[])
    from contextlib import ExitStack
    with ExitStack() as stk:
        for p in _patch_common():
            stk.enter_context(p)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(routes.mark_course_domain_documents(
                course_id=42, body=body, http_request=MagicMock(), user=_user(),
            ))

    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "EMPTY_PAYLOAD"


# ─── Unmark — NOT_FOUND ─────────────────────────────────────────────────

def test_unmark_returns_404_NOT_FOUND_when_no_row():
    from contextlib import ExitStack
    with ExitStack() as stk:
        for p in _patch_common():
            stk.enter_context(p)
        with patch.object(
            routes.SyncCanvasCourseDomainDocRepository, "disable", return_value=False
        ):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(routes.unmark_course_domain_document(
                    course_id=42, file_hash="z" * 16, http_request=MagicMock(), user=_user(),
                ))

    assert exc.value.status_code == 404
    assert exc.value.detail["error"] == "NOT_FOUND"


def test_unmark_happy_path_returns_success():
    from contextlib import ExitStack
    with ExitStack() as stk:
        for p in _patch_common():
            stk.enter_context(p)
        with patch.object(
            routes.SyncCanvasCourseDomainDocRepository, "disable", return_value=True
        ) as disable_called:
            result = asyncio.run(routes.unmark_course_domain_document(
                course_id=42, file_hash="z" * 16, http_request=MagicMock(), user=_user(),
            ))

    assert result["success"] is True
    assert result["course_id"] == 42
    assert result["file_hash"] == "z" * 16
    disable_called.assert_called_once()
