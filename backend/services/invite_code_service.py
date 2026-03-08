"""
Invite Code Service — CRUD + validation for DB-managed invite codes.

Security model:
- Codes are hashed with HMAC-SHA256 using INVITE_SECRET before storage.
- Plaintext code is returned *once* at creation and never stored.
- `code_prefix` (first 6 chars) is stored for admin display.
- `validate_and_use()` uses SELECT … FOR UPDATE to prevent race conditions.
"""
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import get_settings
from backend.core.exceptions import BadRequestException, NotFoundException
from backend.database.models.invite_code import InviteCode, InviteCodeUsage

settings = get_settings()

CODE_PREFIX_LENGTH = 6


# ─── HMAC helpers ────────────────────────────────────────────────────────────

def _hmac_hash(plaintext: str) -> str:
    """Produce hex-encoded HMAC-SHA256 of a plaintext invite code."""
    secret = settings.INVITE_SECRET.encode("utf-8")
    return hmac.new(secret, plaintext.encode("utf-8"), hashlib.sha256).hexdigest()


def _verify_hmac(plaintext: str, expected_hash: str) -> bool:
    """Constant-time comparison of HMAC hashes."""
    return hmac.compare_digest(_hmac_hash(plaintext), expected_hash)


# ─── Service class ───────────────────────────────────────────────────────────

class InviteCodeService:
    """Async service for invite code operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Create ────────────────────────────────────────────────────────

    async def create_code(
        self,
        created_by: uuid.UUID,
        label: Optional[str] = None,
        max_uses: Optional[int] = None,
        expires_at: Optional[datetime] = None,
    ) -> Tuple[InviteCode, str]:
        """
        Generate a new invite code.
        Returns (InviteCode row, plaintext_code).
        The plaintext is shown only once — caller must relay it to the admin.
        """
        plaintext = secrets.token_urlsafe(24)  # ~32 chars
        code_hash = _hmac_hash(plaintext)
        prefix = plaintext[:CODE_PREFIX_LENGTH]

        invite = InviteCode(
            code_hash=code_hash,
            code_prefix=prefix,
            label=label,
            max_uses=max_uses,
            expires_at=expires_at,
            created_by=created_by,
        )
        self.db.add(invite)
        await self.db.flush()
        await self.db.refresh(invite)
        return invite, plaintext

    # ── Read ──────────────────────────────────────────────────────────

    async def list_codes(
        self,
        page: int = 1,
        page_size: int = 20,
        active_only: bool = False,
    ) -> Tuple[List[InviteCode], int]:
        """
        Paginated list of invite codes with total count.
        Returns (codes, total).
        """
        base_q = select(InviteCode)
        count_q = select(func.count(InviteCode.id))

        if active_only:
            base_q = base_q.where(InviteCode.is_active == True)  # noqa: E712
            count_q = count_q.where(InviteCode.is_active == True)  # noqa: E712

        total_result = await self.db.execute(count_q)
        total = total_result.scalar() or 0

        codes_result = await self.db.execute(
            base_q
            .order_by(InviteCode.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        codes = list(codes_result.scalars().all())
        return codes, total

    async def get_code(self, code_id: uuid.UUID) -> InviteCode:
        """Get a single invite code by ID (or raise 404)."""
        invite = await self.db.get(InviteCode, code_id)
        if invite is None:
            raise NotFoundException("Mã mời không tồn tại.")
        return invite

    async def get_usages(
        self,
        code_id: uuid.UUID,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[InviteCodeUsage], int]:
        """Paginated usage records for a specific invite code."""
        # Ensure code exists
        await self.get_code(code_id)

        count_result = await self.db.execute(
            select(func.count(InviteCodeUsage.id))
            .where(InviteCodeUsage.invite_code_id == code_id)
        )
        total = count_result.scalar() or 0

        usages_result = await self.db.execute(
            select(InviteCodeUsage)
            .where(InviteCodeUsage.invite_code_id == code_id)
            .order_by(InviteCodeUsage.used_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        usages = list(usages_result.scalars().all())
        return usages, total

    # ── Update ────────────────────────────────────────────────────────

    async def update_code(
        self,
        code_id: uuid.UUID,
        label: Optional[str] = ...,
        max_uses: Optional[int] = ...,
        is_active: Optional[bool] = ...,
        expires_at: Optional[datetime] = ...,
    ) -> InviteCode:
        """Update editable fields of an invite code."""
        invite = await self.get_code(code_id)

        if label is not ...:
            invite.label = label
        if max_uses is not ...:
            invite.max_uses = max_uses
        if is_active is not ...:
            invite.is_active = is_active
        if expires_at is not ...:
            invite.expires_at = expires_at

        await self.db.flush()
        await self.db.refresh(invite)
        return invite

    async def toggle_active(self, code_id: uuid.UUID) -> InviteCode:
        """Toggle the is_active flag of an invite code."""
        invite = await self.get_code(code_id)
        invite.is_active = not invite.is_active
        await self.db.flush()
        await self.db.refresh(invite)
        return invite

    # ── Delete ────────────────────────────────────────────────────────

    async def delete_code(self, code_id: uuid.UUID) -> None:
        """Hard-delete an invite code and its usages (CASCADE)."""
        invite = await self.get_code(code_id)
        await self.db.delete(invite)
        await self.db.flush()

    # ── Validate & Use (signup flow) ──────────────────────────────────

    async def validate_and_use(
        self,
        plaintext_code: str,
        user_id: uuid.UUID,
    ) -> InviteCode:
        """
        Validate a plaintext code during signup and record usage.

        Uses SELECT … FOR UPDATE to prevent race conditions on
        concurrent signups with the same code.

        Raises BadRequestException on any validation failure.
        """
        code_hash = _hmac_hash(plaintext_code)

        # Row-level lock
        result = await self.db.execute(
            select(InviteCode)
            .where(InviteCode.code_hash == code_hash)
            .with_for_update()
        )
        invite = result.scalar_one_or_none()

        if invite is None:
            raise BadRequestException("Mã mời không hợp lệ.")

        if not invite.is_active:
            raise BadRequestException("Mã mời đã bị vô hiệu hóa.")

        if invite.is_expired:
            raise BadRequestException("Mã mời đã hết hạn.")

        if invite.is_exhausted:
            raise BadRequestException("Mã mời đã đạt giới hạn sử dụng.")

        # Record usage
        usage = InviteCodeUsage(
            invite_code_id=invite.id,
            user_id=user_id,
        )
        self.db.add(usage)
        invite.used_count += 1

        await self.db.flush()
        return invite

    # ── Stats ─────────────────────────────────────────────────────────

    async def get_stats(self) -> Dict[str, Any]:
        """Summary statistics for the admin dashboard."""
        total_result = await self.db.execute(
            select(func.count(InviteCode.id))
        )
        active_result = await self.db.execute(
            select(func.count(InviteCode.id))
            .where(InviteCode.is_active == True)  # noqa: E712
        )
        total_usages_result = await self.db.execute(
            select(func.count(InviteCodeUsage.id))
        )

        return {
            "total_codes": total_result.scalar() or 0,
            "active_codes": active_result.scalar() or 0,
            "total_usages": total_usages_result.scalar() or 0,
        }
