"""
Enrutador Central de la API v1.

Agrupa todos los sub-enrutadores modulares de la aplicación para ser montados en el core principal.
"""

from fastapi import APIRouter
from api.v1.endpoints import equipment, equipment_taxonomy, maintenance, user

api_router = APIRouter()

# Registro del enrutador de usuarios
api_router.include_router(user.router, prefix="/usuarios", tags=["Usuarios"])

# Registro de enrutadores del dominio técnico
api_router.include_router(equipment_taxonomy.router, prefix="/taxonomia", tags=["Taxonomía de Equipos"])
api_router.include_router(equipment.router, prefix="/equipos", tags=["Equipos"])
api_router.include_router(maintenance.router, prefix="/mantenimientos", tags=["Mantenimientos"])