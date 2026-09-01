"""
Rutas y Controladores de la API para el Módulo de Usuarios (Sistema RCM).

Define los endpoints RESTful protegidos y documentados para Swagger/OpenAPI,
gestionando la interacción con Supabase Auth y la base de datos local.
"""

import uuid
from typing import List
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from supabase import Client
from pydantic import EmailStr

from db.session import get_db
from db.supabaseR import get_supabase_admin
from core.security import get_current_user, RoleChecker
from models.user import User, UserRole
from schemas.user import (
    UserCreate, 
    UserUpdate, 
    UserResponse, 
    UserLogin, 
    TokenResponse, 
    TokenRefreshRequest, 
    ForgotPasswordRequest
)
from services import user as user_service
from crud import user as crud_user

router = APIRouter()

@router.post("/registro", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def registrar_usuario(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db),
    supabase_admin: Client = Depends(get_supabase_admin)
):
    """
    * **Ruta:** POST /api/v1/usuarios/registro
    * **Token:** No requiere
    * **Nivel de permiso:** Público (Cualquier visitante o administrador)
    * **Uso:** Recibe los datos personales, rol técnico, turno operativo y contraseña del nuevo trabajador.
    * **Resultado:** Registra de forma segura las credenciales en Supabase Auth y crea el perfil técnico en PostgreSQL de manera atómica con rollback automático ante fallos.
    """
    return await user_service.register_user(db=db, user_in=user_in, supabase_admin=supabase_admin)


@router.post("/login", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def login(
    credentials: UserLogin,
    db: AsyncSession = Depends(get_db),
    supabase_client: Client = Depends(get_supabase_admin)
):
    """
    * **Ruta:** POST /api/v1/usuarios/login
    * **Token:** No requiere
    * **Nivel de permiso:** Público
    * **Uso:** Recibe las credenciales corporativas (email y password) del trabajador.
    * **Resultado:** Valida contra Supabase Auth, confirma que la cuenta esté activa (`is_active: true`) y retorna el par de tokens JWT (`access_token` y `refresh_token`) junto con el perfil completo.
    """
    return await user_service.login_user(db=db, credentials=credentials, supabase_client=supabase_client)


@router.post("/refresh", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def refresh_token(
    payload: TokenRefreshRequest,
    db: AsyncSession = Depends(get_db),
    supabase_client: Client = Depends(get_supabase_admin)
):
    """
    * **Ruta:** POST /api/v1/usuarios/refresh
    * **Token:** No requiere (Se transfiere en el cuerpo JSON de la petición)
    * **Nivel de permiso:** Público
    * **Uso:** Envía el `refresh_token` provisto en el login cuando el access token haya caducado.
    * **Resultado:** Emite un nuevo access token manteniendo la sesión activa del usuario sin requerir reautenticación manual.
    """
    return await user_service.refresh_session(db=db, refresh_token=payload.refresh_token, supabase_client=supabase_client)


@router.post("/recuperar-contrasena", status_code=status.HTTP_200_OK)
async def recuperar_contrasena(
    payload: ForgotPasswordRequest,
    supabase_client: Client = Depends(get_supabase_admin)
):
    """
    * **Ruta:** POST /api/v1/usuarios/recuperar-contrasena
    * **Token:** No requiere
    * **Nivel de permiso:** Público
    * **Uso:** Recibe el correo electrónico registrado del trabajador.
    * **Resultado:** Dispara un correo con enlace seguro de restablecimiento de contraseña gestionado por Supabase Auth.
    """
    return await user_service.request_password_reset(email=payload.email, supabase_client=supabase_client)


@router.get("/me", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def obtener_mi_perfil(current_user: User = Depends(get_current_user)):
    """
    * **Ruta:** GET /api/v1/usuarios/me
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Obtiene la ficha técnica e información de perfil del usuario logueado en la sesión activa.
    * **Resultado:** Retorna los datos asociados al token validado (especialidad, rol, turno y datos de contacto).
    """
    return current_user


@router.get(
    "/", 
    response_model=List[UserResponse], 
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker([UserRole.admin, UserRole.technical_auditor]))]
)
async def listar_usuarios(
    skip: int = Query(0, ge=0, description="Número de registros a omitir para paginación"),
    limit: int = Query(100, ge=1, le=500, description="Límite de registros a recuperar"),
    db: AsyncSession = Depends(get_db)
):
    """
    * **Ruta:** GET /api/v1/usuarios/
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Administrador (`admin`) o Auditor Técnico (`technical_auditor`)
    * **Uso:** Consulta el listado completo y paginado del personal operativo activo en la plataforma RCM.
    * **Resultado:** Retorna un arreglo JSON con los perfiles técnicos de los usuarios que no han sido dados de baja.
    """
    return await crud_user.get_users(db=db, skip=skip, limit=limit)


@router.get("/buscar", response_model=List[UserResponse], status_code=status.HTTP_200_OK)
async def buscar_usuarios(
    nombre: str = Query(..., min_length=2, description="Texto parcial de nombre o apellido"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/usuarios/buscar?nombre={valor}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Filtra usuarios en tiempo real por coincidencia parcial en nombre o apellido (no sensible a mayúsculas).
    * **Resultado:** Retorna una lista con todos los perfiles activos que coincidan con el criterio de búsqueda.
    """
    return await crud_user.search_users_by_name(db, nombre)


@router.get("/buscar-email", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def buscar_usuario_por_email(
    email: EmailStr = Query(..., description="Correo electrónico exacto del usuario"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/usuarios/buscar-email?email={correo}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Busca la información de un usuario mediante su dirección de correo institucional exacta.
    * **Resultado:** Devuelve el perfil completo del usuario. Retorna error 404 si no existe o fue dado de baja.
    """
    return await user_service.get_user_by_email_or_404(db, email)


@router.get("/{id}", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def obtener_usuario(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/usuarios/{id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Pasa el UUID del usuario en la ruta para consultar su ficha técnica completa.
    * **Resultado:** Muestra el perfil solicitado o genera una excepción 404 si no existe en la base de datos.
    """
    return await user_service.get_user_or_404(db, id)


@router.patch("/{id}", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def actualizar_perfil(
    id: uuid.UUID,
    user_in: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** PATCH /api/v1/usuarios/{id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Propietario de la cuenta o Administrador (`admin`)
    * **Uso:** Envía en el cuerpo JSON únicamente los campos a actualizar (teléfono, ficha, turno, etc.).
    * **Resultado:** Aplica los cambios y actualiza el campo `updated_at`. Previene que un usuario común altere su propio rol.
    """
    return await user_service.update_user_profile(db=db, target_user_id=id, user_in=user_in, current_user=current_user)


@router.delete("/{id}", status_code=status.HTTP_200_OK)
async def eliminar_usuario(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    supabase_admin: Client = Depends(get_supabase_admin)
):
    """
    * **Ruta:** DELETE /api/v1/usuarios/{id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Propietario de la cuenta o Administrador (`admin`)
    * **Uso:** Envía el UUID del usuario a eliminar del sistema RCM.
    * **Resultado:** Aplica baja lógica registrando la marca temporal en `deleted_at`, desactiva el flag `is_active` y revoca accesos en Supabase Auth.
    """
    return await user_service.disable_user(db=db, target_user_id=id, current_user=current_user, supabase_admin=supabase_admin)