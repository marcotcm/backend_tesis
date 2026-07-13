from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from api.v1.api import api_router

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