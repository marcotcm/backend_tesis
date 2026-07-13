from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from core.config import settings
from sqlalchemy.pool import NullPool

# Ajustamos el engine para que sea lo más amigable posible con Vercel
engine = create_async_engine(
    settings.DATABASE_URL, 
    echo=False,  # Cambiado a False: El logging excesivo a consola puede causar timeouts en Vercel
    poolclass=NullPool,
    connect_args={
        "server_settings": {"jit": "off"}, # A veces necesario en entornos limitados
        "command_timeout": 60              # Aumentamos el timeout para evitar errores de conexión efímera
    }
)

# Crear la fábrica de sesiones
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# Base para los modelos
class Base(DeclarativeBase):
    pass

# Dependencia para inyectar la sesión en los endpoints
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()