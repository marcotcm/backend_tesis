"""
Módulo de Gestión de Sesiones Asíncronas de Base de Datos.

Configura el motor SQLAlchemy asíncrono utilizando NullPool para entornos
serverless o de escalado dinámico (evitando conexiones inactivas en Supabase/Vercel)
y provee un generador de sesiones para inyección de dependencias en FastAPI.
"""

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from core.config import settings

# Creación del motor asíncrono con connection pooling reutilizable
# Evita abrir y cerrar handshakes SSL en cada solicitud HTTP (~1.7s -> ~50ms)
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,  # Deshabilitado en entornos productivos para optimizar rendimiento de logs
    pool_size=10,  # Conexiones persistentes abiertas en el pool
    max_overflow=20,  # Conexiones adicionales permitidas bajo ráfagas de tráfico
    pool_timeout=30,  # Tiempo máximo de espera para obtener una conexión del pool
    pool_recycle=1800,  # Recicla conexiones cada 30 minutos para prevenir cortes de socket inactivo
    pool_pre_ping=True,  # Verifica la vitalidad del socket antes de reutilizarlo
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