import uuid

from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.user_push_token import UserPushToken


async def register_or_update_token(
    db: AsyncSession,
    user_id: uuid.UUID,
    token: str,
) -> UserPushToken:
    """Registra el token o lo reasigna/reactiva si ya estaba guardado."""
    statement = insert(UserPushToken).values(
        user_id=user_id,
        token=token,
        last_seen_at=func.now(),
    )
    statement = statement.on_conflict_do_update(
        index_elements=[UserPushToken.token],
        set_={
            "user_id": user_id,
            "is_active": True,
            "updated_at": func.now(),
            "last_seen_at": func.now(),
        },
    ).returning(UserPushToken)

    result = await db.execute(statement)
    await db.commit()
    return result.scalar_one()


async def deactivate_token(db: AsyncSession, user_id: uuid.UUID, token: str) -> None:
    """Desactiva únicamente el token perteneciente al usuario autenticado."""
    statement = (
        update(UserPushToken)
        .where(
            UserPushToken.user_id == user_id,
            UserPushToken.token == token,
            UserPushToken.is_active.is_(True),
        )
        .values(is_active=False, updated_at=func.now())
    )
    await db.execute(statement)
    await db.commit()
