from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from core.config import settings

# Crear el motor asíncrono
engine = create_async_engine(settings.DATABASE_URL, echo=True)

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
        yield session