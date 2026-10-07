"""
Capa de Servicios y Reglas de Negocio para Métricas de Equipos.

Garantiza la inyección del usuario en sesión, protege la integridad de los 
datos históricos, centraliza la lógica de negocio para las consultas y 
dispara el análisis predictivo de IA ante anomalías físicas.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional
from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from crud import equipment_metrics as crud_metrics
from models.equipment import Equipment
from models.equipment_metrics import EquipmentMetricHistory
from models.user import User, UserRole
from schemas.equipment_metrics import EquipmentMetricCreate, EquipmentMetricUpdate
from services.ai_predictive_service import ejecutar_analisis_predictivo_ia


async def record_metric(
    db: AsyncSession,
    metric_in: EquipmentMetricCreate,
    current_user: User,
    background_tasks: BackgroundTasks,
) -> EquipmentMetricHistory:
    """
    Registra una nueva lectura vinculándola al usuario en sesión,
    valida umbrales estándar y dispara la IA en segundo plano si hay anomalía.
    """
    metric_data = metric_in.model_dump()
    metric_data["recorded_by"] = current_user.id

    try:
        # 1. Guardar la métrica en la base de datos
        nueva_metrica = await crud_metrics.create_metric(db, obj_in=metric_data)

        # 2. Consultar el equipo para revisar los umbrales de 'standard_metric'
        eq_result = await db.execute(
            select(Equipment).where(Equipment.id == metric_in.equipment_id)
        )
        equipment = eq_result.scalar_one_or_none()

        if equipment and equipment.technical_specifications:
            specs = equipment.technical_specifications
            standard_metric = specs.get("standard_metric", {})

            disparar_ia = False

            # Validación de Temperatura
            if (
                "temperature_celsius" in standard_metric
                and metric_in.temperature_celsius is not None
            ):
                t_min = standard_metric["temperature_celsius"].get("min", -50)
                t_max = standard_metric["temperature_celsius"].get("max", 1000)
                if (
                    metric_in.temperature_celsius < t_min
                    or metric_in.temperature_celsius > t_max
                ):
                    disparar_ia = True

            # Validación de Vibración
            if (
                "vibration_mm_s" in standard_metric
                and metric_in.vibration_mm_s is not None
            ):
                v_min = standard_metric["vibration_mm_s"].get("min", 0)
                v_max = standard_metric["vibration_mm_s"].get("max", 100)
                if (
                    metric_in.vibration_mm_s < v_min
                    or metric_in.vibration_mm_s > v_max
                ):
                    disparar_ia = True

            # Validación dinámica para otras variables dentro de 'specific_metrics'
            if metric_in.specific_metrics:
                for var_name, valor_actual in metric_in.specific_metrics.items(
                    
                ):
                    if var_name in standard_metric:
                        s_min = standard_metric[var_name].get("min")
                        s_max = standard_metric[var_name].get("max")
                        if s_min is not None and valor_actual < s_min:
                            disparar_ia = True
                        if s_max is not None and valor_actual > s_max:
                            disparar_ia = True

            # 3. Si se supera algún estándar, lanzar el análisis profundo con Gemini en segundo plano
            if disparar_ia:
                background_tasks.add_task(
                    ejecutar_analisis_predictivo_ia,
                    db=db,
                    equipment_id=metric_in.equipment_id,
                    trigger_source="Anomalía en Métrica en Tiempo Real",
                    trigger_reference_id=nueva_metrica.id,
                )

        return nueva_metrica

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fallo al registrar la métrica en la base de datos: {str(e)}",
        )


# ==========================================
# FUNCIONES DE SERVICIO PARA LECTURA
# ==========================================
async def get_all_metrics(
    db: AsyncSession, skip: int, limit: int
) -> List[EquipmentMetricHistory]:
    """Servicio para obtener el historial global."""
    return await crud_metrics.get_metrics(db, skip=skip, limit=limit)


async def get_equipment_metrics(
    db: AsyncSession, equipment_id: uuid.UUID, skip: int, limit: int
) -> List[EquipmentMetricHistory]:
    """Servicio para obtener la tendencia de un equipo."""
    return await crud_metrics.get_metrics_by_equipment(
        db, equipment_id=equipment_id, skip=skip, limit=limit
    )


async def get_user_metrics(
    db: AsyncSession, user_id: uuid.UUID, skip: int, limit: int
) -> List[EquipmentMetricHistory]:
    """Servicio para obtener las lecturas registradas por un técnico."""
    return await crud_metrics.get_metrics_by_user(
        db, user_id=user_id, skip=skip, limit=limit
    )


async def get_metrics_by_dates(
    db: AsyncSession,
    start_date: datetime,
    end_date: datetime,
    equipment_id: Optional[uuid.UUID],
    skip: int,
    limit: int,
) -> List[EquipmentMetricHistory]:
    """Servicio para filtrar métricas por fechas con validación de negocio."""
    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error de negocio: La fecha de inicio no puede ser posterior a la fecha de fin.",
        )
    return await crud_metrics.get_metrics_by_date_range(
        db, start_date, end_date, equipment_id, skip, limit
    )


async def get_metric_or_404(
    db: AsyncSession, metric_id: uuid.UUID
) -> EquipmentMetricHistory:
    """Obtiene una lectura o genera un error 404 estructurado."""
    metric = await crud_metrics.get_metric_by_id(db, metric_id)
    if not metric:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registro de métrica no encontrado.",
        )
    return metric


async def update_metric_record(
    db: AsyncSession,
    metric_id: uuid.UUID,
    metric_in: EquipmentMetricUpdate,
    current_user: User,
) -> EquipmentMetricHistory:
    """Aplica una actualización restringida a una métrica existente."""
    db_metric = await get_metric_or_404(db, metric_id)

    if (
        current_user.role != UserRole.admin
        and db_metric.recorded_by != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permisos para modificar una métrica registrada por otro técnico.",
        )

    update_data = metric_in.model_dump(exclude_unset=True)
    if not update_data:
        return db_metric

    return await crud_metrics.update_metric(
        db, db_obj=db_metric, update_data=update_data
    )


async def delete_metric_record(
    db: AsyncSession, metric_id: uuid.UUID, current_user: User
) -> dict:
    """Elimina físicamente una lectura errónea. Restringido exclusivamente a administradores."""
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los administradores pueden eliminar registros históricos del sistema.",
        )

    db_metric = await get_metric_or_404(db, metric_id)
    await crud_metrics.delete_metric(db, db_obj=db_metric)

    return {"detail": "Registro histórico de métrica eliminado permanentemente."}