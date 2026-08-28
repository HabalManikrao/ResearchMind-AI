"""In-app notifications API (spec §11). All notifications are user-scoped."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Notification, User
from app.schemas.research import MessageOut
from app.schemas.scheduling import NotificationOut, UnreadCountOut
from app.security.auth import get_current_user

router = APIRouter(
    prefix="/notifications", tags=["notifications"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read.is_(False))
    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)
    return (await db.execute(stmt)).scalars().all()


@router.get("/unread-count", response_model=UnreadCountOut)
async def unread_count(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    n = (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user.id, Notification.read.is_(False))
        )
    ).scalar_one()
    return UnreadCountOut(unread=n)


@router.post("/{notification_id}/read", response_model=MessageOut)
async def mark_read(
    notification_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    notif = await db.get(Notification, notification_id)
    if notif is None or notif.user_id != user.id:
        raise HTTPException(404, "Notification not found")
    notif.read = True
    await db.commit()
    return MessageOut(message="Marked as read")


@router.post("/read-all", response_model=MessageOut)
async def mark_all_read(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    await db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read.is_(False))
        .values(read=True)
    )
    await db.commit()
    return MessageOut(message="All marked as read")


@router.delete("/{notification_id}", response_model=MessageOut)
async def delete_notification(
    notification_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    notif = await db.get(Notification, notification_id)
    if notif is None or notif.user_id != user.id:
        raise HTTPException(404, "Notification not found")
    await db.delete(notif)
    await db.commit()
    return MessageOut(message="Notification deleted")
