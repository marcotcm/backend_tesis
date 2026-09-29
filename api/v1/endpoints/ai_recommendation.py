import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import get_current_user
from crud import ai_recommendation as crud
from db.session import get_db
from models.user import User
from schemas.ai_recommendation import (AIRecommendationCreate, AIRecommendationResponse,
                                        AIRecommendationStatusUpdate, AIRecommendationUpdate)
from services import ai_recommendation as service

router = APIRouter()


@router.post(
    "/",
    response_model=AIRecommendationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear recomendación de IA",
    description="Registra una recomendación para un equipo. La generación automática de IA se integrará posteriormente.",
)
async def create_recommendation(data: AIRecommendationCreate, db: AsyncSession = Depends(get_db),
                                current_user: User = Depends(get_current_user)):
    """
    * **Ruta:** POST /api/v1/recomendaciones/
    * **Token:** Requiere un token JWT válido.
    * **Nivel de permiso:** Usuario autenticado.
    * **Uso:** Registra una recomendación de IA asociada a un equipo.
    * **Resultado:** Crea la recomendación con estado inicial `Pendiente`.
      La generación automática mediante IA se integrará posteriormente.
    """
    return await service.create(db, data)


@router.get(
    "/",
    response_model=list[AIRecommendationResponse],
    summary="Listar recomendaciones de IA",
    description="Consulta las recomendaciones registradas con paginación.",
)
async def list_recommendations(skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
                               db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    * **Ruta:** GET /api/v1/recomendaciones/
    * **Token:** Requiere un token JWT válido.
    * **Nivel de permiso:** Usuario autenticado.
    * **Uso:** Consulta las recomendaciones registradas con paginación.
    * **Resultado:** Retorna las recomendaciones ordenadas desde la más reciente.
    """
    return await crud.list_all(db, skip, limit)


@router.get(
    "/{id}",
    response_model=AIRecommendationResponse,
    summary="Consultar recomendación de IA",
    description="Obtiene una recomendación mediante su identificador.",
)
async def get_recommendation(id: uuid.UUID, db: AsyncSession = Depends(get_db),
                             current_user: User = Depends(get_current_user)):
    """
    * **Ruta:** GET /api/v1/recomendaciones/{id}
    * **Token:** Requiere un token JWT válido.
    * **Nivel de permiso:** Usuario autenticado.
    * **Uso:** Consulta una recomendación mediante su UUID.
    * **Resultado:** Retorna la recomendación o un error 404 si no existe.
    """
    return await service.get(db, id)


@router.patch(
    "/{id}/status",
    response_model=AIRecommendationResponse,
    summary="Actualizar estado de recomendación",
    description="Acepta, rechaza o devuelve a pendiente una recomendación.",
)
async def update_recommendation_status(id: uuid.UUID, data: AIRecommendationStatusUpdate,
                                       db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    * **Ruta:** PATCH /api/v1/recomendaciones/{id}/status
    * **Token:** Requiere un token JWT válido.
    * **Nivel de permiso:** Usuario autenticado.
    * **Uso:** Cambia el estado a `Pendiente`, `Aceptada` o `Rechazada`.
    * **Resultado:** Al aceptar o rechazar, registra automáticamente quién resolvió
      la recomendación y cuándo ocurrió.
    """
    return await service.set_status(db, id, data, current_user)


@router.patch(
    "/{id}",
    response_model=AIRecommendationResponse,
    summary="Actualizar recomendación de IA",
    description="Actualiza el contenido editable de una recomendación.",
)
async def update_recommendation(id: uuid.UUID, data: AIRecommendationUpdate, db: AsyncSession = Depends(get_db),
                                current_user: User = Depends(get_current_user)):
    """
    * **Ruta:** PATCH /api/v1/recomendaciones/{id}
    * **Token:** Requiere un token JWT válido.
    * **Nivel de permiso:** Usuario autenticado.
    * **Uso:** Actualiza el origen, texto, tipo de predicción o confianza de la recomendación.
    * **Resultado:** Retorna la recomendación actualizada.
    """
    return await service.update(db, id, data)

