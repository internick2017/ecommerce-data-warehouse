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
    # 0.01 = one cent, matches numeric(12,2); compares subtotal (pre-tax/shipping) per order so errors cannot cancel across orders
    ("item_revenue_reconciles_per_order",
     """
     select count(*) from (
       select o.order_gid
       from curated.fact_orders o
       join (select order_gid, sum(line_revenue) as item_total
             from curated.fact_order_items group by order_gid) i using (order_gid)
       where abs(o.subtotal_amount - i.item_total) > 0.01
     ) d
     """),
]


def run_quality_checks(conn):
    """Runs every check, returns [(name, violations)] when all pass.

    If any check has violations, raises QualityError listing ALL failed
    checks (operators get the full picture in one run).
    """
    results = [(name, conn.execute(sql).fetchone()[0]) for name, sql in CHECKS]
    failed = [(n, v) for n, v in results if v != 0]
    if failed:
        detail = ", ".join(f"{n} ({v} violations)" for n, v in failed)
        raise QualityError(f"quality checks failed: {detail}")
    return results
