from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import get_verified_current_user
from db.session import get_db
from models.user import User, UserRole
from models.user_push_token import UserPushToken
from schemas.user_push_token import (
    UserPushTokenCreate,
    UserPushTokenAdminResponse,
    UserPushTokenResponse,
    UserPushTokenSummary,
)
from services import user_push_token as user_push_token_service

router = APIRouter()


def summarize_token(token: UserPushToken) -> UserPushTokenSummary:
    suffix = token.token[-4:] if len(token.token) > 4 else "****"
    return UserPushTokenSummary(
        id=token.id,
        user_id=token.user_id,
        token_suffix=f"...{suffix}",
        is_active=token.is_active,
        created_at=token.created_at,
        updated_at=token.updated_at,
        last_seen_at=token.last_seen_at,
    )


@router.get(
    "/me/push-tokens",
    response_model=list[UserPushTokenSummary],
    summary="Listar mis tokens push",
)
async def list_my_push_tokens(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_verified_current_user),
) -> list[UserPushTokenSummary]:
    tokens = await user_push_token_service.list_user_tokens(
        db, current_user.id, skip, limit
    )
    return [summarize_token(token) for token in tokens]


@router.get(
    "/push-tokens",
    response_model=list[UserPushTokenAdminResponse],
    summary="Listar todos los tokens push completos (administrador)",
)
async def list_all_push_tokens(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_verified_current_user),
) -> list[UserPushTokenAdminResponse]:
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo un administrador puede consultar todos los tokens push.",
        )
    return await user_push_token_service.list_all_tokens(db, skip, limit)


@router.post(
    "/me/push-tokens",
    response_model=UserPushTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Registrar token push del dispositivo",
)
async def register_push_token(
    payload: UserPushTokenCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_verified_current_user),
) -> UserPushToken:
    """Asocia o actualiza el token del dispositivo con el usuario autenticado."""
    return await user_push_token_service.register_token(db, current_user.id, payload.token)


@router.delete(
    "/me/push-tokens",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Desvincular token push del dispositivo",
)
async def unregister_push_token(
    payload: UserPushTokenCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_verified_current_user),
) -> Response:
    """Desactiva el token enviado solo si pertenece al usuario autenticado."""
    await user_push_token_service.unregister_token(db, current_user.id, payload.token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
