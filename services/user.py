import traceback # Importa esto al principio del archivo
from sqlalchemy.ext.asyncio import AsyncSession
from crud import user as crud_user
from schemas.user import UserCreate
from fastapi import HTTPException, status
from supabase import Client

async def register_user(db: AsyncSession, user_in: UserCreate, supabase_admin: Client):
    # 1. Validar unicidad (Lógica local)
    if await crud_user.get_by_email(db, user_in.email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El email ya está registrado.")
    
    if await crud_user.get_by_identification(db, user_in.identification_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La identificación ya existe.")

    # 2. Registrar en Supabase Auth
    try:
        auth_response = supabase_admin.auth.admin.create_user({
            "email": user_in.email,
            "password": user_in.password,
            "email_confirm": True
        })
        user_id = auth_response.user.id
    except Exception as e:
        traceback.print_exc() # <--- ESTO IMPRIME EL ERROR REAL EN LA TERMINAL
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error Supabase: {str(e)}"
        )

    # 3. Crear el perfil profesional en BD local
    try:
        return await crud_user.create(db, user_in, user_id=user_id)
    except Exception as e:
        traceback.print_exc() # <--- ESTO TE DIRÁ SI ES UN 'IntegrityError' o qué falla
        
        # Rollback: Borrar usuario de Supabase si falla la BD
        try:
            supabase_admin.auth.admin.delete_user(user_id)
        except:
            pass # Si falla el borrado, al menos ya tenemos el error de la BD en la terminal
            
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error crítico en BD: {str(e)}"
        )