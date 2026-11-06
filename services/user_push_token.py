import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from crud import user_push_token as crud_user_push_token
from models.user_push_token import UserPushToken


async def list_user_tokens(
    db: AsyncSession,
    user_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
) -> list[UserPushToken]:
    return await crud_user_push_token.list_user_tokens(db, user_id, skip, limit)


async def list_all_tokens(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
) -> list[UserPushToken]:
    return await crud_user_push_token.list_all_tokens(db, skip, limit)


async def register_token(
    db: AsyncSession,
    user_id: uuid.UUID,
    token: str,
) -> UserPushToken:
    return await crud_user_push_token.register_or_update_token(db, user_id, token)


async def unregister_token(db: AsyncSession, user_id: uuid.UUID, token: str) -> None:
    await crud_user_push_token.deactivate_token(db, user_id, token)
