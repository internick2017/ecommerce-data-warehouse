from transform.runner import run_sql_files
from webhook import events

SQL = ["transform/sql/001_schemas.sql", "transform/sql/002_webhook_events.sql"]


def bootstrap(db):
    run_sql_files(db, SQL)


def test_event_seen_roundtrip(db):
    bootstrap(db)
    assert events.event_seen(db, "evt-1") is False
    events.record_event(db, "evt-1", "orders/create", "gid://shopify/Order/1", True, "processed")
    assert events.event_seen(db, "evt-1") is True


def test_record_event_is_idempotent(db):
    bootstrap(db)
    events.record_event(db, "evt-1", "orders/create", "gid://1", True, "processed")
    events.record_event(db, "evt-1", "orders/create", "gid://1", True, "rejected")  # no-op
    rows = db.execute(
        "select status from meta.webhook_events where event_id='evt-1'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "processed"  # first write wins


def test_record_event_persists_fields(db):
    bootstrap(db)
    events.record_event(db, "evt-2", "orders/updated", "gid://shopify/Order/9", True, "processed")
    row = db.execute(
        "select topic, shopify_gid, hmac_valid, status from meta.webhook_events where event_id='evt-2'"
    ).fetchone()
    assert row == ("orders/updated", "gid://shopify/Order/9", True, "processed")
