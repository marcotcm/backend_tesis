import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from crud import user_push_token as crud_user_push_token
from models.user_push_token import UserPushToken


async def register_token(
    db: AsyncSession,
    user_id: uuid.UUID,
    token: str,
) -> UserPushToken:
    return await crud_user_push_token.register_or_update_token(db, user_id, token)


async def unregister_token(db: AsyncSession, user_id: uuid.UUID, token: str) -> None:
    await crud_user_push_token.deactivate_token(db, user_id, token)
