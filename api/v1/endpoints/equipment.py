"""
Endpoints para la gestión de equipos y activos.
"""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from schemas.equipment import EquipmentCreate, EquipmentResponse, EquipmentUpdate
from services import equipment as equipment_service

router = APIRouter()


@router.post(
    "/",
    response_model=EquipmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear equipo",
)
async def crear_equipo(
    equipment_in: EquipmentCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    * **Ruta:** POST /api/v1/equipos/
    * **Token:** No requiere actualmente.
    * **Nivel de permiso:** Público.
    * **Uso:** Registra un activo industrial con su taxonomía, tag, tipo y estado operativo.
    * **Resultado:** Crea el equipo si la taxonomía existe y el tag no está duplicado.
    """
    return await equipment_service.create_equipment(db=db, equipment_in=equipment_in)


@router.get(
    "/",
    response_model=List[EquipmentResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar equipos",
)
async def listar_equipos(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    taxonomy_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    * **Ruta:** GET /api/v1/equipos/
    * **Token:** No requiere actualmente.
    * **Nivel de permiso:** Público.
    * **Uso:** Consulta equipos con paginación y filtro opcional por taxonomía.
    * **Resultado:** Retorna los activos registrados ordenados por nombre.
    """
    if taxonomy_id is not None:
        from crud import equipment as crud_equipment
        return await crud_equipment.get_equipments_by_taxonomy(db=db, taxonomy_id=taxonomy_id)
    return await equipment_service.list_equipments(db=db, skip=skip, limit=limit)


@router.get(
    "/{id}",
    response_model=EquipmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Consultar equipo",
)
async def obtener_equipo(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    * **Ruta:** GET /api/v1/equipos/{id}
    * **Token:** No requiere actualmente.
    * **Nivel de permiso:** Público.
    * **Uso:** Consulta un equipo mediante su UUID.
    * **Resultado:** Retorna el equipo solicitado o un error 404 si no existe.
    """
    return await equipment_service.get_equipment_or_404(db=db, equipment_id=id)


@router.patch(
    "/{id}",
    response_model=EquipmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Actualizar equipo",
)
async def actualizar_equipo(
    id: uuid.UUID,
    equipment_in: EquipmentUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    * **Ruta:** PATCH /api/v1/equipos/{id}
    * **Token:** No requiere actualmente.
    * **Nivel de permiso:** Público.
    * **Uso:** Actualiza parcialmente los datos técnicos y operativos del equipo.
    * **Resultado:** Retorna el equipo actualizado después de validar la taxonomía y el tag.
    """
    return await equipment_service.update_equipment(db=db, equipment_id=id, equipment_in=equipment_in)


@router.delete(
    "/{id}",
    response_model=EquipmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Dar de baja equipo",
)
async def desactivar_equipo(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    * **Ruta:** DELETE /api/v1/equipos/{id}
    * **Token:** No requiere actualmente.
    * **Nivel de permiso:** Público.
    * **Uso:** Da de baja lógicamente un equipo sin borrar su registro.
    * **Resultado:** Retorna el equipo inactivo con su fecha de baja.
    """
    return await equipment_service.deactivate_equipment(db=db, equipment_id=id)
