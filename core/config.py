"""
Módulo de Configuración Global de la Aplicación.

Define la clase Settings que hereda de BaseSettings de Pydantic.
Carga y valida las variables de entorno requeridas desde el archivo .env,
tales como cadenas de conexión a base de datos y credenciales de Supabase.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "RCM Confiabilidad Industrial API"
    VERSION: str = "1.0.0"
    
    # URL de conexión asíncrona a PostgreSQL (e.g., postgresql+asyncpg://...)
    DATABASE_URL: str
    
    # Parámetros de conexión y autenticación con Supabase
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str
    SUPABASE_JWT_SECRET: str

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore"  # Ignora variables sobrantes en el archivo .env para evitar excepciones de validación
    )

# Instancia única reutilizable (Singleton) en toda la aplicación
settings = Settings()