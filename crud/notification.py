from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc, update
from models.notification import Notification
from schemas.notification import NotificationCreate
import uuid

async def create_notification(db: AsyncSession, obj_in: NotificationCreate) -> Notification:
    db_obj = Notification(
        user_id=obj_in.user_id,
        title=obj_in.title,
        message=obj_in.message,
        notification_type=obj_in.notification_type
    )
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def get_user_notifications(db: AsyncSession, user_id: uuid.UUID, skip: int = 0, limit: int = 50):
    """Obtiene las notificaciones específicas del usuario y las globales (user_id IS NULL)"""
    stmt = select(Notification).where(
        (Notification.user_id == user_id) | (Notification.user_id.is_(None))
    ).order_by(desc(Notification.created_at)).offset(skip).limit(limit)
    
    result = await db.execute(stmt)
    return result.scalars().all()

async def mark_notification_as_read(db: AsyncSession, notification_id: uuid.UUID, user_id: uuid.UUID) -> Notification:
    stmt = select(Notification).where(
        Notification.id == notification_id,
        (Notification.user_id == user_id) | (Notification.user_id.is_(None))
    )
    result = await db.execute(stmt)
    db_notif = result.scalar_one_or_none()
    
    if db_notif:
        db_notif.is_read = True
        await db.commit()
        await db.refresh(db_notif)
        
    return db_notif