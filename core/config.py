from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str
    # Agregamos los campos que faltaban para que coincidan con tu .env
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str
    SUPABASE_JWT_SECRET: str

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True, # Mantenlo True para que coincida exactamente con los nombres en mayúsculas
        extra="ignore"       # Esto evita el error de "Extra inputs" si hay variables de más
    )

settings = Settings()