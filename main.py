"""
Punto de Entrada Principal de la Aplicación FastAPI (RCM Confiabilidad Industrial).

Configura el ciclo de vida del servidor, middlewares de CORS, 
manejadores globales de excepciones e incluye el enrutador central de la API.
"""

import logging
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from models.user import User  # Registro explícito del modelo en el metadata de SQLAlchemy
from api.v1.api import api_router
from core.config import settings

# 1. Configuración de Logging del Sistema
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("rcm_backend")

# 2. Inicialización de la Aplicación FastAPI
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend RCM para gestión de confiabilidad operativa industrial y mantenimiento adaptativo.",
    version=settings.VERSION,
    docs_url="/docs",
    redoc_url="/redoc"
)

# 3. Configuración de Middleware CORS (Habilita la integración con Frontend Web y Móvil)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configurar con dominios específicos en entornos de producción
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Manejadores Globales de Excepciones

@app.exception_handler(SQLAlchemyError)
async def database_exception_handler(request: Request, exc: SQLAlchemyError):
    """Captura y loguea fallos a nivel de base de datos sin exponer detalles de infraestructura al cliente."""
    logger.error(f"Error de base de datos en {request.url.path}: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "error": "DatabaseError",
            "message": "El servicio de base de datos no está disponible temporalmente."
        }
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Manejador genérico para capturar excepciones no controladas en tiempo de ejecución."""
    logger.error(f"Error interno no controlado en {request.url.path}: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "InternalServerError",
            "message": "Ha ocurrido un error inesperado en el servidor."
        }
    )

# 5. Inclusión de las Rutas de la API v1
app.include_router(api_router, prefix="/api/v1")

# 6. Endpoint de Monitoreo / Control de Salud (Health Check)
@app.get("/", tags=["Monitoreo"], status_code=status.HTTP_200_OK)
async def health_check():
    """Verifica que el servicio esté en línea y respondiendo adecuadamente."""
    return {
        "status": "online",
        "system": settings.PROJECT_NAME,
        "version": settings.VERSION
    }