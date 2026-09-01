"""
Enrutador Central de la API v1.

Agrupa todos los sub-enrutadores modulares de la aplicación para ser montados en el core principal.
"""

from fastapi import APIRouter
from api.v1.endpoints import user

api_router = APIRouter()

# Registro del enrutador de usuarios
api_router.include_router(user.router, prefix="/usuarios", tags=["Usuarios"])