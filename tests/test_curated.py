from decimal import Decimal

from tests.fixtures import seed_raw
from transform.runner import run_sql_files

ALL_SQL = [
    "transform/sql/001_schemas.sql",
    "transform/sql/010_staging.sql",
    "transform/sql/020_curated.sql",
]


def build(db):
    run_sql_files(db, ALL_SQL[:1])
    seed_raw(db)
    run_sql_files(db, ALL_SQL[1:])


def test_star_schema_tables_exist_with_rows(db):
    build(db)
    for table, expected in [
        ("curated.dim_product", 2),
        ("curated.dim_customer", 2),
        ("curated.fact_orders", 3),
        ("curated.fact_order_items", 3),
    ]:
        assert db.execute(f"select count(*) from {table}").fetchone()[0] == expected


def test_dim_date_covers_order_range(db):
    build(db)
    row = db.execute("select min(date_key), max(date_key) from curated.dim_date").fetchone()
    assert str(row[0]) <= "2026-06-01"


def test_fact_orders_customer_sequence_window(db):
    build(db)
    # Ana has 2 orders -> sequence 1 then 2 (row_number window function)
    rows = db.execute(
        """
        select f.order_gid, f.customer_order_seq
        from curated.fact_orders f
        join curated.dim_customer c on c.customer_key = f.customer_key
        where c.display_name = 'Ana'
        order by f.customer_order_seq
        """
    ).fetchall()
    assert [r[1] for r in rows] == [1, 2]


def test_guest_order_has_null_customer_key(db):
    build(db)
    row = db.execute(
        "select customer_key from curated.fact_orders where order_gid='gid://shopify/Order/3'"
    ).fetchone()
    assert row[0] is None


def test_fact_items_revenue_matches_orders(db):
    build(db)
    items_total = db.execute(
        "select sum(quantity * unit_price) from curated.fact_order_items"
    ).fetchone()[0]
    orders_total = db.execute(
        "select sum(total_amount) from curated.fact_orders"
    ).fetchone()[0]
    assert items_total == orders_total == Decimal("65.00")
