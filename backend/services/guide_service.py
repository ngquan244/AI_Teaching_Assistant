"""
Guide Service
=============
CRUD operations for guide documents stored in the database.
Each guide document corresponds to a panel/feature and can be edited independently.
"""
import logging
import uuid
from typing import List, Optional

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models.guide_document import GuideDocument

logger = logging.getLogger(__name__)


async def list_guides(
    db: AsyncSession,
    *,
    include_unpublished: bool = False,
    visible_panels: Optional[set[str]] = None,
) -> List[GuideDocument]:
    """
    List all guide documents, ordered by sort_order.

    Args:
        db: Async database session.
        include_unpublished: If True, include unpublished guides (admin mode).
        visible_panels: If provided, only return guides whose panel_key is in
                        this set OR whose panel_key is 'overview'/'faq'.
    """
    stmt = select(GuideDocument).order_by(GuideDocument.sort_order)

    if not include_unpublished:
        stmt = stmt.where(GuideDocument.is_published == True)  # noqa: E712

    result = await db.execute(stmt)
    guides = list(result.scalars().all())

    # Filter by visible panels (non-admin users)
    if visible_panels is not None:
        # Always show overview and faq regardless of panel visibility
        always_visible = {"overview", "faq"}
        guides = [
            g for g in guides
            if g.panel_key in always_visible or g.panel_key in visible_panels
        ]

    return guides


async def get_guide_by_panel_key(
    db: AsyncSession,
    panel_key: str,
) -> Optional[GuideDocument]:
    """Get a single guide document by its panel_key."""
    stmt = select(GuideDocument).where(GuideDocument.panel_key == panel_key)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_guide(
    db: AsyncSession,
    *,
    panel_key: str,
    title: str,
    content: str = "",
    description: Optional[str] = None,
    icon_name: Optional[str] = None,
    sort_order: int = 0,
    is_published: bool = True,
) -> GuideDocument:
    """Create a new guide document."""
    guide = GuideDocument(
        panel_key=panel_key,
        title=title,
        content=content,
        description=description,
        icon_name=icon_name,
        sort_order=sort_order,
        is_published=is_published,
    )
    db.add(guide)
    await db.flush()
    await db.refresh(guide)
    logger.info("Created guide document: panel_key=%s, title=%s", panel_key, title)
    return guide


async def update_guide(
    db: AsyncSession,
    panel_key: str,
    *,
    title: Optional[str] = None,
    content: Optional[str] = None,
    description: Optional[str] = None,
    icon_name: Optional[str] = None,
    sort_order: Optional[int] = None,
    is_published: Optional[bool] = None,
) -> Optional[GuideDocument]:
    """
    Update an existing guide document. Only non-None fields are updated.
    Returns the updated document, or None if not found.
    """
    guide = await get_guide_by_panel_key(db, panel_key)
    if not guide:
        return None

    if title is not None:
        guide.title = title
    if content is not None:
        guide.content = content
    if description is not None:
        guide.description = description
    if icon_name is not None:
        guide.icon_name = icon_name
    if sort_order is not None:
        guide.sort_order = sort_order
    if is_published is not None:
        guide.is_published = is_published

    await db.flush()
    await db.refresh(guide)
    logger.info("Updated guide document: panel_key=%s", panel_key)
    return guide


async def delete_guide(
    db: AsyncSession,
    panel_key: str,
) -> bool:
    """Delete a guide document by panel_key. Returns True if deleted."""
    stmt = delete(GuideDocument).where(GuideDocument.panel_key == panel_key)
    result = await db.execute(stmt)
    deleted = result.rowcount > 0
    if deleted:
        logger.info("Deleted guide document: panel_key=%s", panel_key)
    return deleted
