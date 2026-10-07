"""
Endpoints para la gestión de equipos y activos.
"""

import uuid
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from core.security import get_current_user
from models.user import User
from schemas.equipment import (
    EquipmentBulkImportResponse,
    EquipmentCreate,
    EquipmentResponse,
    EquipmentUpdate,
    UsageTimeUpdate,
)
from services import equipment_bulk as equipment_bulk_service
from services import equipment as equipment_service

router = APIRouter()

@router.post(
    "/bulk",
    response_model=EquipmentBulkImportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Importar equipos en lote",
)
async def importar_equipos(
    taxonomy_id: Optional[uuid.UUID] = Query(
        None,
        description="UUID de la taxonomía; úsalo para resolver nombres duplicados.",
    ),
    taxonomy_name: Optional[str] = Query(
        None,
        min_length=1,
        description="Nombre de la taxonomía; debe ser único si no se envía taxonomy_id.",
    ),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Importa un CSV o XLSX de forma transaccional: todo el lote o ninguno."""
    return await equipment_bulk_service.import_equipments(
        db=db,
        taxonomy_id=taxonomy_id,
        taxonomy_name=taxonomy_name,
        file=file,
        user=current_user,
    )


@router.get(
    "/export",
    summary="Exportar equipos de una taxonomía",
)
async def exportar_equipos(
    taxonomy_id: uuid.UUID = Query(..., description="UUID de la taxonomía seleccionada."),
    file_format: Literal["xlsx", "csv"] = Query("xlsx", alias="format"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    contents, media_type, filename = await equipment_bulk_service.export_equipments(
        db=db,
        taxonomy_id=taxonomy_id,
        file_format=file_format,
    )
    return Response(
        content=contents,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@router.post(
    "/",
    response_model=EquipmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear equipo",
)
async def crear_equipo(
    equipment_in: EquipmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    * **Ruta:** POST /api/v1/equipos/
    * **Token:** Requiere (Bearer JWT).
    * **Nivel de permiso:** Usuario Autenticado.
    * **Uso:** Registra un activo industrial con su taxonomía, tag, tipo y estado operativo.
    * **Resultado:** Crea el equipo si la taxonomía existe y el tag no está duplicado.
    """
    return await equipment_service.create_equipment(db=db, equipment_in=equipment_in, user_id=current_user.id)

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
    current_user: User = Depends(get_current_user),
):
    """
    * **Ruta:** GET /api/v1/equipos/
    * **Token:** Requiere (Bearer JWT).
    * **Nivel de permiso:** Usuario Autenticado.
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
    current_user: User = Depends(get_current_user),
):
    """
    * **Ruta:** GET /api/v1/equipos/{id}
    * **Token:** Requiere (Bearer JWT).
    * **Nivel de permiso:** Usuario Autenticado.
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
    current_user: User = Depends(get_current_user),
):
    """
    * **Ruta:** PATCH /api/v1/equipos/{id}
    * **Token:** Requiere (Bearer JWT).
    * **Nivel de permiso:** Usuario Autenticado.
    * **Uso:** Actualiza parcialmente los datos técnicos y operativos del equipo.
    * **Resultado:** Retorna el equipo actualizado después de validar la taxonomía y el tag.
    """
    return await equipment_service.update_equipment(db=db, equipment_id=id, equipment_in=equipment_in, user_id=current_user.id)

@router.patch(
    "/{id}/tiempo-uso",
    response_model=EquipmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Gestionar tiempo de uso",
)
async def actualizar_tiempo_uso(
    id: uuid.UUID,
    usage_in: UsageTimeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    * **Ruta:** PATCH /api/v1/equipos/{id}/tiempo-uso
    * **Token:** Requiere (Bearer JWT).
    * **Nivel de permiso:** Usuario Autenticado.
    * **Uso:** Suma, resta o sobrescribe los minutos de uso de un equipo específico.
    * **operation:** Puede ser `add` (sumar), `subtract` (restar) o `set` (reemplazar).
    """
    return await equipment_service.update_equipment_usage_time(db=db, equipment_id=id, usage_in=usage_in, user_id=current_user.id)

@router.delete(
    "/{id}",
    response_model=EquipmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Dar de baja equipo",
)
async def desactivar_equipo(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    * **Ruta:** DELETE /api/v1/equipos/{id}
    * **Token:** Requiere (Bearer JWT).
    * **Nivel de permiso:** Usuario Autenticado.
    * **Uso:** Da de baja lógicamente un equipo sin borrar su registro.
    * **Resultado:** Retorna el equipo inactivo con su fecha de baja.
    """
    return await equipment_service.deactivate_equipment(db=db, equipment_id=id)