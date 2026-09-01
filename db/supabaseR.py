"""
Cliente Administrativo de Supabase.

Instancia el cliente SDK de Supabase con permisos elevados (Service Role)
para la gestión segura de autenticación en el servidor (bypasseando RLS y administrando auth.users).
"""

from supabase import create_client, Client
from core.config import settings

def get_supabase_admin() -> Client:
    """
    Inicializa y retorna una instancia del cliente Supabase con la clave de servicio.
    Valida la disponibilidad del submódulo de administración (GoTrue Admin).
    """
    client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    if client.auth.admin is None:
        raise RuntimeError("El cliente Supabase no pudo inicializar el módulo 'admin'. Verifique la Service Role Key.")
    return client