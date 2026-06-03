import sqlite3

import pytest


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()
