from decimal import Decimal

from tests.fixtures import seed_raw
from transform.runner import run_sql_files

SQL = ["transform/sql/001_schemas.sql", "transform/sql/010_staging.sql"]


def test_staging_orders_typed_and_complete(db):
    run_sql_files(db, SQL[:1])
    seed_raw(db)
    run_sql_files(db, SQL[1:])
    rows = db.execute(
        "select order_gid, total_amount, customer_gid from staging.orders order by order_gid"
    ).fetchall()
    assert len(rows) == 3
    assert rows[0][1] == Decimal("30.00")
    guest = db.execute(
        "select customer_gid from staging.orders where order_gid='gid://shopify/Order/3'"
    ).fetchone()
    assert guest[0] is None


def test_staging_order_items_flattened(db):
    run_sql_files(db, SQL[:1])
    seed_raw(db)
    run_sql_files(db, SQL[1:])
    count = db.execute("select count(*) from staging.order_items").fetchone()[0]
    assert count == 3
    row = db.execute(
        "select quantity, unit_price from staging.order_items "
        "where line_item_gid='gid://shopify/LineItem/1'"
    ).fetchone()
    assert row == (2, Decimal("15.00"))


def test_staging_rebuild_is_repeatable(db):
    run_sql_files(db, SQL[:1])
    seed_raw(db)
    run_sql_files(db, SQL[1:])
    run_sql_files(db, SQL[1:])  # full rebuild must not raise or duplicate
    assert db.execute("select count(*) from staging.orders").fetchone()[0] == 3


def test_zero_item_order_in_orders_but_not_items(db):
    from tests.fixtures import order
    from load import pg_loader
    from tests.fixtures import NOW
    run_sql_files(db, SQL[:1])
    seed_raw(db)
    pg_loader.upsert_raw(db, "orders", [order(9, None, "0.00", [])],
                         load_id=1, extracted_at=NOW)
    run_sql_files(db, SQL[1:])
    assert db.execute("select count(*) from staging.orders").fetchone()[0] == 4
    assert db.execute("select count(*) from staging.order_items").fetchone()[0] == 3
