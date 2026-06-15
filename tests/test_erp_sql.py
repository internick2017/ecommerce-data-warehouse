from transform.runner import run_sql_files


def test_raw_erp_costs_table_created(db):
    run_sql_files(db, ["transform/sql/001_schemas.sql"])
    cols = {
        r[0]
        for r in db.execute(
            "select column_name from information_schema.columns "
            "where table_schema='raw' and table_name='erp_costs'"
        ).fetchall()
    }
    assert {"sku", "unit_cost", "on_hand", "erp_updated_at", "loaded_at"} <= cols


def test_raw_erp_costs_upsert_by_sku(db):
    run_sql_files(db, ["transform/sql/001_schemas.sql"])
    db.execute(
        "insert into raw.erp_costs (sku, unit_cost, on_hand, erp_updated_at) "
        "values ('SKU-1', 6.00, 100, now())"
    )
    db.execute(
        "insert into raw.erp_costs (sku, unit_cost, on_hand, erp_updated_at) "
        "values ('SKU-1', 7.50, 90, now()) "
        "on conflict (sku) do update set unit_cost=excluded.unit_cost, on_hand=excluded.on_hand"
    )
    row = db.execute("select unit_cost, on_hand from raw.erp_costs where sku='SKU-1'").fetchone()
    assert row == (7.50, 90)
