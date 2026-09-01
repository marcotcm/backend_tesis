"""
Módulo de Gestión de Sesiones Asíncronas de Base de Datos.

Configura el motor SQLAlchemy asíncrono utilizando NullPool para entornos
serverless o de escalado dinámico (evitando conexiones inactivas en Supabase/Vercel)
y provee un generador de sesiones para inyección de dependencias en FastAPI.
"""

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool
from core.config import settings

# Creación del motor asíncrono optimizado para PostgreSQL
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,  # Deshabilitado en entornos productivos para optimizar rendimiento de logs
    poolclass=NullPool,  # Delega la gestión de conexiones al pooler de Supabase (PgBouncer/Supavisor)
    connect_args={
        "server_settings": {"jit": "off"},  # Desactiva JIT para reducir la sobrecarga de memoria en consultas ligeras
        "command_timeout": 60  # Límite de tiempo en segundos para sentencias SQL
    }
)

# Fábrica de sesiones asíncronas
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Mantiene los atributos cargados en memoria tras el commit
    autoflush=False
)

class Base(DeclarativeBase):
    """Clase base declarativa de la cual heredarán todos los modelos de SQLAlchemy."""
    pass

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Generador asíncrono para la inyección de dependencias de la sesión de base de datos.
    Garantiza el cierre adecuado de la transacción y liberación del recurso al finalizar la solicitud.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()