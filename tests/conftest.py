import os

import psycopg
import pytest

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://dw:dw@localhost:5433/ecommerce_dw"
)


@pytest.fixture()
def db():
    """Fresh connection; drops all pipeline schemas so each test starts clean."""
    conn = psycopg.connect(DATABASE_URL, autocommit=True)
    for schema in ("raw", "staging", "curated", "meta"):
        conn.execute(f"drop schema if exists {schema} cascade")
    yield conn
    conn.close()
