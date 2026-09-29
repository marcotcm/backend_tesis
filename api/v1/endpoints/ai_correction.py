import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import get_current_user
from crud import ai_correction as crud
from db.session import get_db
from models.user import User
from schemas.ai_correction import AICorrectionCreate, AICorrectionResponse, AICorrectionUpdate
from services import ai_correction as service

router = APIRouter()


@router.post(
    "/",
    response_model=AICorrectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar corrección humana",
    description="Registra la corrección de un experto sobre una recomendación de IA resuelta.",
)
async def create_correction(data: AICorrectionCreate, db: AsyncSession = Depends(get_db),
                            current_user: User = Depends(get_current_user)):
    """
    * **Ruta:** POST /api/v1/correcciones/
    * **Token:** Requiere un token JWT válido.
    * **Nivel de permiso:** Usuario autenticado.
    * **Uso:** Registra la corrección de un experto sobre una recomendación de IA.
    * **Resultado:** Guarda una única corrección para una recomendación aceptada o rechazada.
      El usuario corrector se toma del token autenticado.
    """
    return await service.create(db, data, current_user)


@router.get(
    "/",
    response_model=list[AICorrectionResponse],
    summary="Listar correcciones humanas",
    description="Consulta las correcciones humanas registradas con paginación.",
)
async def list_corrections(skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
                           db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    * **Ruta:** GET /api/v1/correcciones/
    * **Token:** Requiere un token JWT válido.
    * **Nivel de permiso:** Usuario autenticado.
    * **Uso:** Consulta las correcciones humanas registradas con paginación.
    * **Resultado:** Retorna las correcciones ordenadas desde la más reciente.
    """
    return await crud.list_all(db, skip, limit)


@router.get(
    "/{id}",
    response_model=AICorrectionResponse,
    summary="Consultar corrección humana",
    description="Obtiene una corrección humana mediante su identificador.",
)
async def get_correction(id: uuid.UUID, db: AsyncSession = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    """
    * **Ruta:** GET /api/v1/correcciones/{id}
    * **Token:** Requiere un token JWT válido.
    * **Nivel de permiso:** Usuario autenticado.
    * **Uso:** Consulta una corrección humana mediante su UUID.
    * **Resultado:** Retorna la corrección solicitada o un error 404 si no existe.
    """
    return await service.get(db, id)


@router.patch(
    "/{id}",
    response_model=AICorrectionResponse,
    summary="Actualizar corrección humana",
    description="Actualiza el texto de una corrección humana.",
)
async def update_correction(id: uuid.UUID, data: AICorrectionUpdate, db: AsyncSession = Depends(get_db),
                            current_user: User = Depends(get_current_user)):
    """Actualiza el texto de una corrección existente."""
    return await service.update(db, id, data)

