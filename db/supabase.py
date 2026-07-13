from supabase import create_client
from core.config import settings

def get_supabase_admin():
    # Asegúrate de que settings.SUPABASE_SERVICE_ROLE_KEY sea la clave que empieza por "sb_secret_"
    client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    
    # Esto es un chequeo rápido para ver si el admin está cargado
    if client.auth.admin is None:
        raise Exception("El cliente de Supabase no cargó el módulo 'admin'. Revisa si la clave es 'service_role'.")
        
    return client