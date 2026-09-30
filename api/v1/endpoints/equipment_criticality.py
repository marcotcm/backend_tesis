import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import get_current_user
from crud import equipment_criticality as crud
from db.session import get_db
from models.user import User
from schemas.equipment_criticality import EquipmentCriticalityCreate, EquipmentCriticalityResponse, EquipmentCriticalityUpdate
from services import equipment_criticality as service

router = APIRouter()


@router.post(
    "/",
    response_model=EquipmentCriticalityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear evaluación de criticidad",
    description="Registra la evaluación de criticidad de un equipo industrial.",
)
async def create_criticality(data: EquipmentCriticalityCreate, db: AsyncSession = Depends(get_db),
                             current_user: User = Depends(get_current_user)):
    """
    * **Ruta:** POST /api/v1/criticidad/
    * **Token:** Requiere un token JWT válido.
    * **Nivel de permiso:** Usuario autenticado.
    * **Uso:** Registra la evaluación de criticidad de un equipo industrial.
    * **Resultado:** Guarda los impactos de seguridad, ambiente, operación y costo,
      junto con el RPN y el nivel de criticidad. El evaluador se toma del usuario autenticado.
    """
    return await service.create(db, data, current_user)


@router.get(
    "/",
    response_model=list[EquipmentCriticalityResponse],
    summary="Listar evaluaciones de criticidad",
    description="Consulta las evaluaciones de criticidad registradas, opcionalmente filtradas por equipo.",
)
async def list_criticalities(skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
                             equipment_id: Optional[uuid.UUID] = None, db: AsyncSession = Depends(get_db),
                             current_user: User = Depends(get_current_user)):
    """
    * **Ruta:** GET /api/v1/criticidad/
    * **Token:** Requiere un token JWT válido.
    * **Nivel de permiso:** Usuario autenticado.
    * **Uso:** Consulta evaluaciones de criticidad con paginación y filtro opcional por equipo.
    * **Resultado:** Retorna las evaluaciones ordenadas desde la más reciente.
    """
    if equipment_id:
        obj = await crud.get_by_equipment(db, equipment_id)
        return [obj] if obj else []
    return await crud.list_all(db, skip, limit)


@router.get(
    "/{id}",
    response_model=EquipmentCriticalityResponse,
    summary="Consultar evaluación de criticidad",
    description="Obtiene una evaluación de criticidad mediante su identificador.",
)
async def get_criticality(id: uuid.UUID, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(get_current_user)):
    """
    * **Ruta:** GET /api/v1/criticidad/{id}
    * **Token:** Requiere un token JWT válido.
    * **Nivel de permiso:** Usuario autenticado.
    * **Uso:** Consulta una evaluación de criticidad mediante su UUID.
    * **Resultado:** Retorna la evaluación solicitada o un error 404 si no existe.
    """
    return await service.get(db, id)


@router.patch(
    "/{id}",
    response_model=EquipmentCriticalityResponse,
    summary="Actualizar evaluación de criticidad",
    description="Actualiza las puntuaciones o el nivel de criticidad de un equipo.",
)
async def update_criticality(id: uuid.UUID, data: EquipmentCriticalityUpdate, db: AsyncSession = Depends(get_db),
                             current_user: User = Depends(get_current_user)):
    """
    * **Ruta:** PATCH /api/v1/criticidad/{id}
    * **Token:** Requiere un token JWT válido.
    * **Nivel de permiso:** Usuario autenticado.
    * **Uso:** Actualiza parcialmente las puntuaciones o el nivel de criticidad.
    * **Resultado:** Guarda la nueva evaluación y actualiza el evaluador y la fecha.
    """
    return await service.update(db, id, data, current_user)

