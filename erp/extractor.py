"""SQL-based extraction of cost/inventory from the legacy ERP (dbo.product_costs).

The cursor is injected (a real pyodbc cursor in production, a fake in tests), so
this module has no pyodbc dependency and the SQL is fully testable.
"""

COLUMNS = ("sku", "unit_cost", "on_hand", "updated_at")
_BASE_SQL = "SELECT sku, unit_cost, on_hand, updated_at FROM dbo.product_costs"


def extract_costs(cursor, updated_since=None):
    """Return cost rows as dicts. With updated_since, only newer rows (incremental)."""
    if updated_since is None:
        cursor.execute(_BASE_SQL + " ORDER BY updated_at")
    else:
        cursor.execute(_BASE_SQL + " WHERE updated_at > ? ORDER BY updated_at", updated_since)
    return [dict(zip(COLUMNS, row)) for row in cursor.fetchall()]
