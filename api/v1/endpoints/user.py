from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from supabase import Client
from db.session import get_db
from db.supabase import get_supabase_admin
from schemas.user import UserCreate, UserResponse
from services import user
from core.security import verify_token
from db.supabase import get_supabase_admin

router = APIRouter()

# Endpoint protegido: requiere un token válido
@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_in: UserCreate, 
    db: AsyncSession = Depends(get_db),
    supabase_admin: Client = Depends(get_supabase_admin)
    # token: dict = Depends(verify_token) # Agrega esto después
):
    return await user.register_user(db, user_in, supabase_admin)