from datetime import datetime, timezone

from load import pg_loader
from transform.runner import run_sql_file

NOW = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)


def bootstrap(db):
    run_sql_file(db, "transform/sql/001_schemas.sql")


def test_start_and_finish_load(db):
    bootstrap(db)
    load_id = pg_loader.start_load(db)
    assert load_id >= 1
    pg_loader.finish_load(db, load_id, status="SUCCESS",
                          rows_extracted=10, rows_loaded=9, rows_rejected=1)
    row = db.execute(
        "select status, rows_loaded, finished_at from meta.load_audit where load_id=%s",
        (load_id,),
    ).fetchone()
    assert row[0] == "SUCCESS"
    assert row[1] == 9
    assert row[2] is not None


def test_upsert_is_idempotent(db):
    bootstrap(db)
    records = [
        {"id": "gid://shopify/Order/1", "name": "#1001"},
        {"id": "gid://shopify/Order/2", "name": "#1002"},
    ]
    pg_loader.upsert_raw(db, "orders", records, load_id=1, extracted_at=NOW)
    pg_loader.upsert_raw(db, "orders", records, load_id=2, extracted_at=NOW)
    count = db.execute("select count(*) from raw.orders").fetchone()[0]
    assert count == 2
    load_id = db.execute(
        "select load_id from raw.orders where shopify_gid='gid://shopify/Order/1'"
    ).fetchone()[0]
    assert load_id == 2  # last write wins


def test_insert_reject(db):
    bootstrap(db)
    pg_loader.insert_reject(db, "orders", {"bad": True}, "totalPriceSet: missing", load_id=1)
    row = db.execute("select entity, reason from raw.rejects").fetchone()
    assert row == ("orders", "totalPriceSet: missing")


def test_watermark_roundtrip(db):
    bootstrap(db)
    assert pg_loader.get_watermark(db, "orders") is None
    pg_loader.set_watermark(db, "orders", NOW)
    assert pg_loader.get_watermark(db, "orders") == NOW
    later = datetime(2026, 6, 13, tzinfo=timezone.utc)
    pg_loader.set_watermark(db, "orders", later)
    assert pg_loader.get_watermark(db, "orders") == later
