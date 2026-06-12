from transform.runner import run_sql_file


def test_bootstrap_creates_schemas_and_tables(db):
    run_sql_file(db, "transform/sql/001_schemas.sql")
    tables = {
        (r[0], r[1])
        for r in db.execute(
            "select table_schema, table_name from information_schema.tables "
            "where table_schema in ('raw','meta')"
        ).fetchall()
    }
    assert ("raw", "orders") in tables
    assert ("raw", "products") in tables
    assert ("raw", "customers") in tables
    assert ("raw", "rejects") in tables
    assert ("meta", "load_audit") in tables
    assert ("meta", "watermarks") in tables


def test_bootstrap_is_idempotent(db):
    run_sql_file(db, "transform/sql/001_schemas.sql")
    run_sql_file(db, "transform/sql/001_schemas.sql")  # must not raise
