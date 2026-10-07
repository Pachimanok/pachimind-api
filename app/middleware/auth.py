from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader

from app.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Scopes definidos por API key
SCOPE_PERSONAL = "personal"
SCOPE_AI = "ai_context"
SCOPE_PUBLIC = "public"


def get_scope(api_key: str = Security(api_key_header)) -> str:
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="X-API-Key requerido")

    key_map: dict[str, str] = settings.api_keys
    scope = key_map.get(api_key)
    if scope is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="API Key inválida")
    return scope
