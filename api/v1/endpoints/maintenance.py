"""
Endpoints para la gestión de mantenimientos.
"""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from schemas.maintenance import MaintenanceCreate, MaintenanceResponse, MaintenanceUpdate
from services import maintenance as maintenance_service

router = APIRouter()


@router.post(
    "/",
    response_model=MaintenanceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear mantenimiento",
)
async def crear_mantenimiento(
    maintenance_in: MaintenanceCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    * **Ruta:** POST /api/v1/mantenimientos/
    * **Token:** No requiere actualmente.
    * **Nivel de permiso:** Público.
    * **Uso:** Registra un plan de mantenimiento preventivo, predictivo,
      correctivo o adaptativo basado en IA.
    * **Resultado:** Crea el mantenimiento si el equipo asociado existe.
    """
    return await maintenance_service.create_maintenance(db=db, maintenance_in=maintenance_in)


@router.get(
    "/",
    response_model=List[MaintenanceResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar mantenimientos",
)
async def listar_mantenimientos(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    equipment_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    * **Ruta:** GET /api/v1/mantenimientos/
    * **Token:** No requiere actualmente.
    * **Nivel de permiso:** Público.
    * **Uso:** Consulta planes de mantenimiento con paginación y filtro opcional por equipo.
    * **Resultado:** Retorna los mantenimientos registrados ordenados desde el más reciente.
    """
    if equipment_id is not None:
        from crud import maintenance as crud_maintenance
        return await crud_maintenance.get_maintenances_by_equipment(db=db, equipment_id=equipment_id)
    return await maintenance_service.list_maintenances(db=db, skip=skip, limit=limit)


@router.get(
    "/{id}",
    response_model=MaintenanceResponse,
    status_code=status.HTTP_200_OK,
    summary="Consultar mantenimiento",
)
async def obtener_mantenimiento(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    * **Ruta:** GET /api/v1/mantenimientos/{id}
    * **Token:** No requiere actualmente.
    * **Nivel de permiso:** Público.
    * **Uso:** Consulta un plan de mantenimiento mediante su UUID.
    * **Resultado:** Retorna el mantenimiento solicitado o un error 404 si no existe.
    """
    return await maintenance_service.get_maintenance_or_404(db=db, maintenance_id=id)


@router.patch(
    "/{id}",
    response_model=MaintenanceResponse,
    status_code=status.HTTP_200_OK,
    summary="Actualizar mantenimiento",
)
async def actualizar_mantenimiento(
    id: uuid.UUID,
    maintenance_in: MaintenanceUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    * **Ruta:** PATCH /api/v1/mantenimientos/{id}
    * **Token:** No requiere actualmente.
    * **Nivel de permiso:** Público.
    * **Uso:** Actualiza parcialmente el plan, tipo, frecuencia o estado.
    * **Resultado:** Retorna el mantenimiento actualizado después de validar el equipo.
    """
    return await maintenance_service.update_maintenance(db=db, maintenance_id=id, maintenance_in=maintenance_in)


@router.delete(
    "/{id}",
    response_model=MaintenanceResponse,
    status_code=status.HTTP_200_OK,
    summary="Dar de baja mantenimiento",
)
async def desactivar_mantenimiento(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    * **Ruta:** DELETE /api/v1/mantenimientos/{id}
    * **Token:** No requiere actualmente.
    * **Nivel de permiso:** Público.
    * **Uso:** Da de baja lógicamente un plan de mantenimiento.
    * **Resultado:** Retorna el mantenimiento inactivo con su fecha de baja.
    """
    return await maintenance_service.deactivate_maintenance(db=db, maintenance_id=id)
