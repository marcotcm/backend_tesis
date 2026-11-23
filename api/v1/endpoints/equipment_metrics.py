"""
Rutas y Controladores de la API para el Módulo de Historial de Métricas (Sistema RCM).

Define los endpoints RESTful protegidos y documentados para Swagger/OpenAPI,
gestionando la interacción con la base de datos local para la telemetría de equipos.
"""

import uuid
from typing import Any, Dict, List, Optional
from datetime import datetime
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import get_current_user, RoleChecker, verify_supabase_token
from crud.user import get_user_by_id
from db.session import get_db
from models.user import User, UserRole
from schemas.equipment_metrics import EquipmentMetricCreate, EquipmentMetricUpdate, EquipmentMetricResponse
from services import equipment_metrics as metrics_service

router = APIRouter()
optional_bearer = HTTPBearer(auto_error=False)


class IoTReadingItem(BaseModel):
    tag_number: Optional[str] = None
    equipment_id: Optional[uuid.UUID] = None
    temperature_celsius: Optional[float] = None
    vibration_mm_s: Optional[float] = None
    operating_hours: Optional[float] = None
    pressure_psi: Optional[float] = None
    flow_rate_bpd: Optional[float] = None
    motor_amps: Optional[float] = None
    liquid_level_pct: Optional[float] = None
    rpm: Optional[float] = None
    specific_metrics: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None

    @field_validator("temperature_celsius")
    @classmethod
    def check_temp(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < -50 or v > 1000):
            raise ValueError("La temperatura debe estar entre -50°C y 1000°C.")
        return v

    @field_validator("vibration_mm_s")
    @classmethod
    def check_vib(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("La vibración no puede ser negativa.")
        return v


class IoTBatchIngestRequest(BaseModel):
    source: str = Field(default="edge-gateway", min_length=1, max_length=100)
    readings: List[IoTReadingItem] = Field(..., min_length=1, max_length=200)


async def _resolve_iot_actor_user_id(
    db: AsyncSession,
    credentials: Optional[HTTPAuthorizationCredentials],
    x_iot_key: Optional[str],
) -> uuid.UUID:
    # 1. Machine-to-Machine X-IoT-Key cuando IOT_INGEST_API_KEY está configurado
    if settings.IOT_INGEST_API_KEY and x_iot_key and x_iot_key == settings.IOT_INGEST_API_KEY:
        stmt = (
            select(User.id)
            .where(User.is_active == True)
            .order_by((User.role == UserRole.admin).desc())
            .limit(1)
        )
        actor_id = (await db.execute(stmt)).scalar_one_or_none()
        if not actor_id:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No existe un usuario activo de servicio para registrar telemetría IoT.",
            )
        return actor_id

    # 2. Sesión Bearer JWT estándar
    if credentials and credentials.credentials:
        token_payload = verify_supabase_token(credentials)
        user_id_str = token_payload.get("sub")
        if user_id_str:
            try:
                user_uuid = uuid.UUID(user_id_str)
            except ValueError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="UUID de usuario inválido en token.")
            user = await get_user_by_id(db, user_id=user_uuid)
            if user and user.is_active:
                return user.id

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Se requiere Bearer JWT válido o cabecera X-IoT-Key autorizada para ingesta IoT.",
    )


@router.post("/iot-ingest", status_code=status.HTTP_201_CREATED, summary="Ingesta Industrial IoT en Lote por TAG")
async def ingestar_telemetria_iot(
    payload: IoTBatchIngestRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(optional_bearer),
    x_iot_key: Optional[str] = Header(None, alias="X-IoT-Key"),
):
    """
    Endpoint de alta frecuencia para pasarelas PLC / OPC-UA / Modbus / Node-RED / MQTT.
    Acepta hasta 200 lecturas por llamada referenciadas por TAG de planta y emite eventos
    instantáneos por WebSocket hacia la Sala de Control SCADA.
    """
    actor_user_id = await _resolve_iot_actor_user_id(db, credentials, x_iot_key)
    return await metrics_service.ingest_iot_batch(
        db=db,
        source=payload.source,
        readings=[r.model_dump() for r in payload.readings],
        actor_user_id=actor_user_id,
        background_tasks=background_tasks,
    )

@router.post("/", response_model=EquipmentMetricResponse, status_code=status.HTTP_201_CREATED)
async def registrar_metrica(
    metric_in: EquipmentMetricCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** POST /api/v1/metricas/
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Recibe variables de condición operativa (Temperatura, Vibración, horas, etc.) para un equipo.
    * **Resultado:** Registra la lectura en la base de datos, asociando irrevocablemente el ID del técnico en sesión como autor de la medición.
    """
    return await metrics_service.record_metric(db=db, metric_in=metric_in, current_user=current_user, background_tasks=background_tasks )

@router.get("/", response_model=List[EquipmentMetricResponse], status_code=status.HTTP_200_OK)
async def listar_metricas_globales(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/metricas/
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Consulta el listado general y paginado de las últimas métricas capturadas en toda la planta.
    * **Resultado:** Retorna un arreglo JSON ordenado cronológicamente con el historial de variables operativas.
    """
    return await metrics_service.get_all_metrics(db=db, skip=skip, limit=limit)

@router.get("/equipo/{equipment_id}", response_model=List[EquipmentMetricResponse], status_code=status.HTTP_200_OK)
async def historial_por_equipo(
    equipment_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/metricas/equipo/{equipment_id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Recupera la curva de tendencia de variables físicas de una máquina en específico.
    * **Resultado:** Devuelve todas las lecturas asociadas a un equipo particular para facilitar el análisis predictivo.
    """
    return await metrics_service.get_equipment_metrics(db=db, equipment_id=equipment_id, skip=skip, limit=limit)

@router.get("/usuario/{user_id}", response_model=List[EquipmentMetricResponse], status_code=status.HTTP_200_OK)
async def historial_por_usuario(
    user_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/metricas/usuario/{user_id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Realiza una auditoría sobre el trabajo de campo de un trabajador específico.
    * **Resultado:** Lista el historial cronológico de todas las mediciones ingresadas por el usuario consultado.
    """
    return await metrics_service.get_user_metrics(db=db, user_id=user_id, skip=skip, limit=limit)

@router.get("/buscar/fecha", response_model=List[EquipmentMetricResponse], status_code=status.HTTP_200_OK)
async def historial_por_rango_fechas(
    fecha_inicio: datetime = Query(..., description="Fecha de inicio (ISO 8601)"),
    fecha_fin: datetime = Query(..., description="Fecha de fin (ISO 8601)"),
    equipo_id: Optional[uuid.UUID] = Query(None, description="UUID del equipo (Opcional)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/metricas/buscar/fecha
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Filtra el historial operativo dentro de una ventana temporal exacta, opcionalmente acotado a un solo equipo.
    * **Resultado:** Retorna las lecturas físicas que coincidan con el periodo de fechas indicado, útil para investigar fallas.
    """
    return await metrics_service.get_metrics_by_dates(
        db=db, 
        start_date=fecha_inicio, 
        end_date=fecha_fin, 
        equipment_id=equipo_id, 
        skip=skip, 
        limit=limit
    )

@router.get("/{id}", response_model=EquipmentMetricResponse, status_code=status.HTTP_200_OK)
async def obtener_metrica_por_id(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** GET /api/v1/metricas/{id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Usuario Autenticado (Cualquier Rol)
    * **Uso:** Pide el detalle técnico exacto de un solo registro de inspección mediante su identificador.
    * **Resultado:** Muestra la telemetría, notas y datos del registro individual, o genera un 404 si no existe.
    """
    return await metrics_service.get_metric_or_404(db, id)

@router.patch("/{id}", response_model=EquipmentMetricResponse, status_code=status.HTTP_200_OK)
async def actualizar_metrica(
    id: uuid.UUID,
    metric_in: EquipmentMetricUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    * **Ruta:** PATCH /api/v1/metricas/{id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Autor original de la métrica o Administrador (`admin`)
    * **Uso:** Permite corregir exclusivamente anotaciones textuales o métricas adicionales flexibles.
    * **Resultado:** Aplica los cambios a las notas, manteniendo inmutables los valores físicos duros por reglas de integridad.
    """
    return await metrics_service.update_metric_record(db=db, metric_id=id, metric_in=metric_in, current_user=current_user)

@router.delete("/{id}", status_code=status.HTTP_200_OK)
async def purgar_metrica(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RoleChecker([UserRole.admin]))
):
    """
    * **Ruta:** DELETE /api/v1/metricas/{id}
    * **Token:** Requiere (Bearer JWT)
    * **Nivel de permiso:** Exclusivo Administrador (`admin`)
    * **Uso:** Elimina de manera definitiva una lectura física errónea que altere la curva de IA o los KPIs.
    * **Resultado:** Borra el registro de la tabla sin posibilidad de recuperación (Hard Delete).
    """
    return await metrics_service.delete_metric_record(db=db, metric_id=id, current_user=current_user)