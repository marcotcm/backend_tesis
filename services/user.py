"""
Capa de Servicios y Reglas de Negocio para la Gestión de Usuarios.

Coordina las operaciones entre Supabase Auth y PostgreSQL garantizando
atomicidad (rollback en el proveedor de identidad si falla la persistencia local).
"""

import uuid
import traceback
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from supabase import Client
from supabase_auth.errors import AuthApiError
from pydantic import EmailStr

from crud import user as crud_user
from schemas.user import UserCreate, UserUpdate, UserLogin
from models.user import User, UserRole

async def register_user(db: AsyncSession, user_in: UserCreate, supabase_admin: Client) -> User:
    """
    Registra un usuario de forma atómica.
    1. Valida unicidad local de correo y cédula.
    2. Crea la cuenta en Supabase Auth.
    3. Persiste el perfil en PostgreSQL (con rollback en Supabase ante excepciones).
    """
    if await crud_user.get_user_by_email(db, user_in.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="El correo electrónico ya se encuentra registrado en el sistema."
        )
    
    if await crud_user.get_user_by_identification(db, user_in.identification_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="La cédula de identidad ya se encuentra asignada a otro trabajador."
        )

    # Registro en Supabase Auth
    try:
        auth_response = supabase_admin.auth.admin.create_user({
            "email": user_in.email,
            "password": user_in.password,
            "email_confirm": True
        })
        auth_user_id = uuid.UUID(auth_response.user.id)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Error en el servicio de autenticación externo: {str(e)}"
        )

    # Persistencia local con mecanismo de compensación (Rollback)
    try:
        return await crud_user.create_user(db, obj_in=user_in, auth_user_id=auth_user_id)
    except Exception as e:
        traceback.print_exc()
        try:
            # Elimina el usuario recién creado en Auth si falla la base de datos
            supabase_admin.auth.admin.delete_user(str(auth_user_id))
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Fallo al guardar el perfil local. Operación revertida: {str(e)}"
        )

async def login_user(db: AsyncSession, credentials: UserLogin, supabase_client: Client) -> dict:
    """
    Autentica al usuario contra Supabase Auth y valida el estado operativo en PostgreSQL.
    """
    try:
        auth_response = supabase_client.auth.sign_in_with_password({
            "email": credentials.email,
            "password": credentials.password
        })
        
        user_uuid = uuid.UUID(auth_response.user.id)
        local_user = await crud_user.get_user_by_id(db, user_uuid)
        
        if not local_user or not local_user.is_active or local_user.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="Esta cuenta ha sido inhabilitada o dada de baja administrativamente."
            )
            
        return {
            "access_token": auth_response.session.access_token,
            "refresh_token": auth_response.session.refresh_token,
            "token_type": "bearer",
            "user": local_user
        }
    except AuthApiError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Credenciales de acceso incorrectas."
        )

async def refresh_session(db: AsyncSession, refresh_token: str, supabase_client: Client) -> dict:
    """Renueva los tokens JWT utilizando un refresh token activo."""
    try:
        auth_response = supabase_client.auth.refresh_session(refresh_token)
        user_uuid = uuid.UUID(auth_response.user.id)
        local_user = await crud_user.get_user_by_id(db, user_uuid)
        
        if not local_user or not local_user.is_active or local_user.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="La cuenta asociada ha sido desactivada."
            )
            
        return {
            "access_token": auth_response.session.access_token,
            "refresh_token": auth_response.session.refresh_token,
            "token_type": "bearer",
            "user": local_user
        }
    except AuthApiError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="El token de refresco no es válido o ha expirado."
        )

async def request_password_reset(email: EmailStr, supabase_client: Client) -> dict:
    """Envía el correo de restablecimiento de contraseña mediante el proveedor de Auth."""
    try:
        supabase_client.auth.reset_password_for_email(email)
        return {"detail": "Si el correo existe en la plataforma, se ha enviado el enlace de restablecimiento."}
    except AuthApiError as e:
        # Captura errores específicos de validación de Supabase Auth
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Error en el servicio de correo de autenticación: {e.message}"
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Error interno al procesar la solicitud de recuperación."
        )

async def get_user_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    """Obtiene un usuario por ID o genera un error 404 estructurado."""
    user = await crud_user.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado.")
    return user

async def get_user_by_email_or_404(db: AsyncSession, email: str) -> User:
    """Obtiene un usuario por Correo o genera un error 404 estructurado."""
    user = await crud_user.get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado.")
    return user

async def update_user_profile(
    db: AsyncSession, 
    target_user_id: uuid.UUID, 
    user_in: UserUpdate, 
    current_user: User,
    supabase_admin: Optional[Client] = None
) -> User:
    """
    Actualiza el perfil garantizando permisos, unicidad de datos y sincronización con Supabase Auth.
    Convierte el modelo a un diccionario excluyendo campos no enviados (exclude_unset=True)
    y previene que usuarios comunes alteren roles o su estado activo.
    """
    # 1. Validación de permisos: Solo el propio usuario o un Administrador
    if current_user.id != target_user_id and current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="No tiene permisos para modificar datos de otro usuario."
        )
    
    target_user = await get_user_or_404(db, target_user_id)

    # 2. Extracción limpia: solo campos explícitamente enviados en la solicitud JSON
    update_dict = user_in.model_dump(exclude_unset=True)

    # 3. Control de privilegios: descartar campos administrativos si no es admin (sin reasignar None)
    if current_user.role != UserRole.admin:
        update_dict.pop("role", None)
        update_dict.pop("is_active", None)

    # 4. Validación de unicidad si se actualiza la cédula
    if "identification_id" in update_dict and update_dict["identification_id"] != target_user.identification_id:
        existing_id = await crud_user.get_user_by_identification(db, update_dict["identification_id"])
        if existing_id and existing_id.id != target_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="La cédula de identidad ingresada ya se encuentra registrada por otro usuario."
            )

    # 5. Sincronización y unicidad si se actualiza el correo electrónico
    old_email = target_user.email
    if "email" in update_dict and update_dict["email"] != target_user.email:
        existing_email = await crud_user.get_user_by_email(db, update_dict["email"])
        if existing_email and existing_email.id != target_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El correo electrónico ingresado ya se encuentra registrado."
            )
        
        # Sincronización con Supabase Auth
        if supabase_admin:
            try:
                supabase_admin.auth.admin.update_user_by_id(
                    str(target_user_id),
                    {"email": update_dict["email"], "email_confirm": True}
                )
            except Exception as e:
                traceback.print_exc()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Error al sincronizar el nuevo correo con el proveedor de autenticación: {str(e)}"
                )

    # 6. Si no hay modificaciones tras aplicar los filtros, retornar el estado actual
    if not update_dict:
        return target_user

    # 7. Persistencia local pasando el diccionario limpio
    try:
        return await crud_user.update_user(db, db_obj=target_user, update_data=update_dict)
    except Exception as e:
        # Mecanismo de compensación: revertir correo en Supabase ante error en Postgres
        if supabase_admin and "email" in update_dict and update_dict["email"] != old_email:
            try:
                supabase_admin.auth.admin.update_user_by_id(
                    str(target_user_id),
                    {"email": old_email, "email_confirm": True}
                )
            except Exception:
                pass
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al actualizar el perfil en la base de datos local: {str(e)}"
        )

async def disable_user(db: AsyncSession, target_user_id: uuid.UUID, current_user: User, supabase_admin: Client) -> dict:
    """Aplica soft-delete local y revoca definitivamente el acceso eliminando la cuenta en Supabase Auth."""
    if current_user.id != target_user_id and current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="No tiene permisos para dar de baja este usuario."
        )
    
    target_user = await get_user_or_404(db, target_user_id)
    await crud_user.soft_delete_user(db, db_obj=target_user)
    
    try:
        supabase_admin.auth.admin.delete_user(str(target_user_id))
    except Exception:
        pass  # Si el usuario ya fue eliminado en Auth, se mantiene la coherencia local
        
    return {"detail": "Usuario inhabilitado y accesos revocados correctamente."}