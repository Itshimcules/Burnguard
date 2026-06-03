from __future__ import annotations

import sqlite3

from .db import get_virtual_key
from .models import VirtualKey


class AuthError(ValueError):
    pass


def extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise AuthError("Missing Authorization bearer token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthError("Authorization must be Bearer <virtual-key>")
    return token.strip()


def validate_virtual_key(conn: sqlite3.Connection, authorization: str | None, model: str | None = None) -> VirtualKey:
    api_key = extract_bearer_token(authorization)
    virtual_key = get_virtual_key(conn, api_key)
    if virtual_key is None:
        raise AuthError("Unknown virtual API key")
    if not virtual_key.enabled:
        raise AuthError("Virtual API key is disabled")
    if model and virtual_key.allowed_models and model not in virtual_key.allowed_models:
        raise AuthError(f"Model '{model}' is not allowed for this virtual key")
    return virtual_key
