from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import get_verified_current_user
from db.session import get_db
from models.user import User
from models.user_push_token import UserPushToken
from schemas.user_push_token import UserPushTokenCreate, UserPushTokenResponse
from services import user_push_token as user_push_token_service

router = APIRouter()


@router.post(
    "",
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
    "",
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
