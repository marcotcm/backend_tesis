"""
Módulo CRUD (Create, Read, Update, Delete) para la entidad User.

Encapsula todas las operaciones directas contra la base de datos PostgreSQL,
utilizando la sintaxis select() y transacciones asíncronas de SQLAlchemy 2.0.
"""

import uuid
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models.user import User
from schemas.user import UserCreate

async def create_user(db: AsyncSession, obj_in: UserCreate, auth_user_id: uuid.UUID) -> User:
    """Inserta un nuevo registro de usuario vinculándolo al UUID asignado por Supabase Auth."""
    user_data = obj_in.model_dump()
    user_data.pop("password", None)  # El password no se almacena en la tabla pública
    user_data["id"] = auth_user_id
    
    db_obj = User(**user_data)
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> Optional[User]:
    """Recupera un usuario por su clave primaria siempre que no esté eliminado lógicamente."""
    result = await db.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    return result.scalars().first()

async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    """Busca un usuario mediante su dirección de correo electrónico institucional."""
    result = await db.execute(
        select(User).where(User.email == email, User.deleted_at.is_(None))
    )
    return result.scalars().first()

async def get_user_by_identification(db: AsyncSession, identification_id: str) -> Optional[User]:
    """Busca un usuario mediante su cédula de identidad."""
    result = await db.execute(
        select(User).where(User.identification_id == identification_id, User.deleted_at.is_(None))
    )
    return result.scalars().first()

async def search_users_by_name(db: AsyncSession, query_name: str) -> List[User]:
    """Filtra usuarios cuyo nombre o apellido contenga la subcadena dada (Case-Insensitive)."""
    result = await db.execute(
        select(User).where(
            (User.first_name.ilike(f"%{query_name}%")) | (User.last_name.ilike(f"%{query_name}%")),
            User.deleted_at.is_(None)
        )
    )
    return list(result.scalars().all())

async def get_users(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[User]:
    """Retorna una lista paginada de todos los usuarios activos en la base de datos."""
    result = await db.execute(
        select(User).where(User.deleted_at.is_(None)).offset(skip).limit(limit)
    )
    return list(result.scalars().all())

async def update_user(db: AsyncSession, db_obj: User, update_data: dict) -> User:
    """
    Aplica modificaciones parciales dinámicas a un registro existente.
    Recibe un diccionario filtrado (update_data) e itera únicamente sobre 
    las claves enviadas por el cliente, evitando sobreescribir campos con None.
    """
    for field, value in update_data.items():
        if hasattr(db_obj, field):
            setattr(db_obj, field, value)
            
    db_obj.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj

async def soft_delete_user(db: AsyncSession, db_obj: User) -> User:
    """Marca el usuario como inactivo y registra la fecha de borrado lógico."""
    db_obj.deleted_at = datetime.now(timezone.utc)
    db_obj.is_active = False
    await db.commit()
    await db.refresh(db_obj)
    return db_obj