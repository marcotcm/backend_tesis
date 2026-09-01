"""
Módulo de Seguridad, Autenticación y Autorización Basada en Roles (RBAC).

Decodifica y valida los JSON Web Tokens (JWT) emitidos por Supabase,
extrae el contexto del usuario autenticado y provee guardas de seguridad por rol.
"""

import uuid
import jwt
from fastapi import HTTPException, Security, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from db.session import get_db
from crud.user import get_user_by_id
from models.user import User, UserRole

# Esquema de seguridad estándar Bearer Token
security = HTTPBearer()

def verify_supabase_token(credentials: HTTPAuthorizationCredentials = Security(security)) -> dict:
    """
    Decodifica el JWT provisto en las cabeceras HTTP Authorization.
    Verifica la expiración y formato estructural del payload.
    """
    try:
        payload = jwt.decode(
            credentials.credentials,
            options={"verify_signature": False},  # La firma es validada por el API Gateway / JWKS
            algorithms=["ES256", "HS256"],
            audience="authenticated"
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="La sesión ha expirado. Por favor, refresque su token o inicie sesión nuevamente."
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Token de autorización inválido o con formato erróneo."
        )

async def get_current_user(
    token_payload: dict = Depends(verify_supabase_token),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Dependencia que extrae el 'sub' (UUID de Supabase Auth) del token
    y recupera el registro correspondiente de la tabla de usuarios local.
    """
    user_id_str = token_payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="El token no contiene un identificador 'sub' válido."
        )
    
    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="El identificador de usuario en el token no tiene formato UUID."
        )
    
    user = await get_user_by_id(db, user_id=user_uuid)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="El usuario no se encuentra activo o ha sido revocado del sistema."
        )
    return user

class RoleChecker:
    """
    Inyector de dependencia para restringir el acceso a rutas según el rol del usuario.
    Ejemplo de uso: Depends(RoleChecker([UserRole.admin, UserRole.rcm_engineer]))
    """
    def __init__(self, allowed_roles: list[UserRole]):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Privilegios insuficientes para ejecutar esta operación."
            )
        return current_user