import pytest

from tests.fixtures import seed_raw
from transform.quality import QualityError, run_quality_checks
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


def test_clean_build_passes_all_checks(db):
    build(db)
    results = run_quality_checks(db)
    assert all(violations == 0 for _, violations in results)


def test_missing_fact_order_raises(db):
    build(db)
    db.execute("delete from curated.fact_order_items where order_gid='gid://shopify/Order/3'")
    db.execute("delete from curated.fact_orders where order_gid='gid://shopify/Order/3'")
    with pytest.raises(QualityError, match="fact_orders_matches_staging"):
        run_quality_checks(db)


def test_corrupted_item_price_raises(db):
    build(db)
    db.execute(
        "update curated.fact_order_items set line_revenue = line_revenue + 5 "
        "where line_item_gid='gid://shopify/LineItem/1'"
    )
    with pytest.raises(QualityError, match="item_revenue_reconciles_per_order"):
        run_quality_checks(db)
