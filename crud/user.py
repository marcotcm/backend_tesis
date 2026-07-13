import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models.user import User
from schemas.user import UserCreate

async def create(db: AsyncSession, obj_in: UserCreate, user_id: uuid.UUID) -> User:
    # 1. Convertimos el modelo Pydantic a diccionario
    user_data = obj_in.model_dump()
    
    # 2. Eliminamos 'password' para que no cause conflictos con la tabla SQL
    user_data.pop("password", None)
    
    # 3. Agregamos el UUID que viene desde Supabase Auth
    user_data["id"] = user_id
    
    # 4. Instanciamos el modelo con los datos limpios y el nuevo ID
    db_obj = User(**user_data)
    
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    
    return db_obj

async def get_by_email(db: AsyncSession, email: str):
    result = await db.execute(select(User).where(User.email == email))
    return result.scalars().first()

async def get_by_identification(db: AsyncSession, identification_id: str):
    result = await db.execute(select(User).where(User.identification_id == identification_id))
    return result.scalars().first()