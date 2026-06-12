"""Post-transform data quality gates. Any violation fails the pipeline run."""


class QualityError(Exception):
    pass


CHECKS = [
    ("fact_orders_matches_staging",
     """
     select abs((select count(*) from curated.fact_orders)
              - (select count(*) from staging.orders))
     """),
    ("no_orphan_order_items",
     """
     select count(*) from curated.fact_order_items i
     left join curated.fact_orders o using (order_gid)
     where o.order_gid is null
     """),
    ("no_duplicate_product_gids",
     """
     select count(*) from (
       select product_gid from curated.dim_product
       group by product_gid having count(*) > 1
     ) d
     """),
    ("no_duplicate_customer_gids",
     """
     select count(*) from (
       select customer_gid from curated.dim_customer
       group by customer_gid having count(*) > 1
     ) d
     """),
    ("item_revenue_reconciles_with_orders",
     """
     select count(*) from (
       select 1
       where abs(coalesce((select sum(line_revenue) from curated.fact_order_items), 0)
               - coalesce((select sum(total_amount) from curated.fact_orders), 0)) > 0.01
     ) d
     """),
]


def run_quality_checks(conn):
    """Returns [(name, violations)]. Raises QualityError on the first failure."""
    results = []
    for name, sql in CHECKS:
        violations = conn.execute(sql).fetchone()[0]
        results.append((name, violations))
        if violations != 0:
            raise QualityError(f"quality check failed: {name} ({violations} violations)")
    return results
