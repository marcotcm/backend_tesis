from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from api.v1.api import api_router
import uvicorn
from fastapi.openapi.utils import get_openapi

app = FastAPI(
    title="Sistema RCM Backend API",
    description="Backend para gestión RCM de activos críticos",
    version="1.0.0"
)

# Manejador global de excepciones para mantener la API profesional
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"message": "Error interno del servidor", "detail": str(exc)},
    )

# Incluir rutas
app.include_router(api_router, prefix="/api/v1")

@app.get("/")
def health_check():
    return {"status": "online", "message": "API RCM operativa"}

def custom_openapi():
   
    
    # Generamos el esquema base con tus rutas reales de FastAPI
    openapi_schema = get_openapi(
        title="GreenLive API & External Services",
        version="1.0.0",
        description="Documentación unificada. Nota: Las rutas directas de Supabase no pasan por este backend.",
        routes=app.routes,
    )
    
    # URL de tu proyecto de Supabase (reemplázala por la tuya)
    supabase_url = "https://seomdmgnzdulnkwjdgmv.supabase.co"

    # 1. Inyectamos visualmente el LOGIN directo a Supabase
    openapi_schema["paths"]["/auth/v1/token?grant_type=password"] = {
        "post": {
            "tags": ["Autenticación Directa (Supabase)"],
            "summary": "Iniciar Sesión (Directo a Supabase)",
            "description": f"⚠️ **Llamar directamente a:** `{supabase_url}/auth/v1/token?grant_type=password`\n\nNo pasa por FastAPI para evitar latencia.",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "email": {"type": "string", "format": "email", "example": "usuario@ejemplo.com"},
                                "password": {"type": "string", "example": "mi_contrasena_segura"}
                            },
                            "required": ["email", "password"]
                        }
                    }
                }
            },
            "responses": {
                "200": {
                    "description": "Sesión iniciada. Devuelve access_token y refresh_token."
                }
            }
        }
    }

    # 2. Inyectamos visualmente el REFRESH directo a Supabase
    openapi_schema["paths"]["/auth/v1/token?grant_type=refresh_token"] = {
        "post": {
            "tags": ["Autenticación Directa (Supabase)"],
            "summary": "Refrescar Token (Directo a Supabase)",
            "description": f"⚠️ **Llamar directamente a:** `{supabase_url}/auth/v1/token?grant_type=refresh_token`\n\nNo pasa por FastAPI.",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "refresh_token": {"type": "string", "example": "tu_refresh_token_aqui"}
                            },
                            "required": ["refresh_token"]
                        }
                    }
                }
            },
            "responses": {
                "200": {
                    "description": "Token renovado con éxito."
                }
            }
        }
    }

    app.openapi_schema = openapi_schema
    return app.openapi_schema