from transform.runner import run_sql_files

SQL = ["transform/sql/001_schemas.sql", "transform/sql/002_webhook_events.sql"]


def test_webhook_events_table_created(db):
    run_sql_files(db, SQL)
    cols = {
        r[0]
        for r in db.execute(
            "select column_name from information_schema.columns "
            "where table_schema='meta' and table_name='webhook_events'"
        ).fetchall()
    }
    assert {"event_id", "topic", "shopify_gid", "hmac_valid", "status", "received_at"} <= cols


def test_webhook_events_status_check_and_idempotent(db):
    run_sql_files(db, SQL)
    run_sql_files(db, SQL)  # idempotent re-run must not raise
    db.execute(
        "insert into meta.webhook_events (event_id, status) values ('e1', 'received')"
    )
    db.execute(
        "insert into meta.webhook_events (event_id, status) values ('e1', 'processed') "
        "on conflict (event_id) do nothing"
    )
    rows = db.execute(
        "select status from meta.webhook_events where event_id='e1'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 'received'
