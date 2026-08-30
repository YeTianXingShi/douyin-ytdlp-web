from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings


bearer = HTTPBearer(auto_error=False)


def require_admin(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    if not settings.admin_token:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN is not configured")
    if not credentials or credentials.scheme.lower() != "bearer" or not secrets.compare_digest(
        credentials.credentials, settings.admin_token
    ):
        raise HTTPException(status_code=401, detail="Administrator authentication required")
