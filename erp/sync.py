"""Incremental ERP cost/inventory sync into raw.erp_costs (watermark-driven)."""
from erp.extractor import extract_costs
from load import pg_loader

ENTITY = "erp_costs"

_UPSERT = """
insert into raw.erp_costs (sku, unit_cost, on_hand, erp_updated_at)
values (%s, %s, %s, %s)
on conflict (sku) do update set
    unit_cost = excluded.unit_cost,
    on_hand = excluded.on_hand,
    erp_updated_at = excluded.erp_updated_at,
    loaded_at = now()
"""


def sync_costs(pg_conn, erp_cursor):
    """Pull cost rows changed since the watermark, upsert into raw.erp_costs,
    advance the watermark. Returns {'rows_synced', 'new_watermark'}."""
    since = pg_loader.get_watermark(pg_conn, ENTITY)
    rows = extract_costs(erp_cursor, updated_since=since)

    max_updated = since
    for r in rows:
        pg_conn.execute(_UPSERT, (r["sku"], r["unit_cost"], r["on_hand"], r["updated_at"]))
        ts = r["updated_at"]
        if max_updated is None or ts > max_updated:
            max_updated = ts

    if rows and max_updated is not None:
        pg_loader.set_watermark(pg_conn, ENTITY, max_updated)

    return {"rows_synced": len(rows), "new_watermark": max_updated}
