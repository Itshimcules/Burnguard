import pytest

from token_governor.auth import AuthError, validate_virtual_key
from token_governor.db import create_virtual_key, init_db
from token_governor.models import VirtualKey


def test_virtual_key_validation_works(conn):
    init_db(conn)
    key = create_virtual_key(conn, VirtualKey(None, "tg_sk_auth", "Auth", "demo", ["gpt-4o-mini"], 1, 10, 1))
    assert validate_virtual_key(conn, "Bearer tg_sk_auth", "gpt-4o-mini").id == key.id
    with pytest.raises(AuthError):
        validate_virtual_key(conn, "Bearer tg_sk_auth", "gpt-4.1")
