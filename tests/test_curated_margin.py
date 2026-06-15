from decimal import Decimal

from tests.fixtures import seed_raw
from transform.runner import run_sql_files

BOOTSTRAP = ["transform/sql/001_schemas.sql"]
TRANSFORMS = ["transform/sql/010_staging.sql", "transform/sql/020_curated.sql"]


def build_with_costs(db, costs_sql=None):
    run_sql_files(db, BOOTSTRAP)
    seed_raw(db)
    if costs_sql:
        db.execute(costs_sql)
    run_sql_files(db, TRANSFORMS)


def test_margin_computed_when_cost_present(db):
    build_with_costs(
        db,
        "insert into raw.erp_costs (sku, unit_cost, on_hand, erp_updated_at) "
        "values ('SKU-1', 6.00, 100, now())",
    )
    row = db.execute(
        "select unit_cost, line_cost, line_margin from curated.fact_order_items "
        "where sku='SKU-1'"
    ).fetchone()
    assert row[0] == Decimal("6.00")
    assert row[1] == Decimal("12.00")
    assert row[2] == Decimal("18.00")


def test_margin_null_when_no_cost(db):
    build_with_costs(db)
    row = db.execute(
        "select unit_cost, line_cost, line_margin from curated.fact_order_items where sku='SKU-2'"
    ).fetchone()
    assert row == (None, None, None)


def test_dim_inventory_built(db):
    build_with_costs(
        db,
        "insert into raw.erp_costs (sku, unit_cost, on_hand, erp_updated_at) "
        "values ('SKU-1', 6.00, 100, now())",
    )
    row = db.execute(
        "select on_hand, unit_cost from curated.dim_inventory where sku='SKU-1'"
    ).fetchone()
    assert row == (100, Decimal("6.00"))


def test_existing_curated_still_builds(db):
    build_with_costs(db)
    total = db.execute("select sum(line_revenue) from curated.fact_order_items").fetchone()[0]
    assert total == Decimal("65.00")
