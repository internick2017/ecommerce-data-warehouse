from datetime import datetime, timezone
from decimal import Decimal

from erp.extractor import extract_costs


class FakeCursor:
    """Records execute() calls and returns canned rows. Mimics a pyodbc cursor."""

    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        return self

    def fetchall(self):
        return self._rows


ROWS = [
    ("SKU-1", Decimal("8.25"), 10, datetime(2026, 6, 1, tzinfo=timezone.utc)),
    ("SKU-2", Decimal("4.00"), 50, datetime(2026, 6, 2, tzinfo=timezone.utc)),
]


def test_full_extract_no_where_clause():
    cur = FakeCursor(ROWS)
    out = extract_costs(cur)
    sql, params = cur.executed[0]
    assert "where" not in sql.lower()
    assert params == ()
    assert out[0] == {"sku": "SKU-1", "unit_cost": Decimal("8.25"),
                      "on_hand": 10, "updated_at": datetime(2026, 6, 1, tzinfo=timezone.utc)}
    assert len(out) == 2


def test_incremental_extract_passes_watermark():
    cur = FakeCursor([ROWS[1]])
    since = datetime(2026, 6, 1, tzinfo=timezone.utc)
    out = extract_costs(cur, updated_since=since)
    sql, params = cur.executed[0]
    assert "where updated_at > ?" in sql.lower()
    assert params == (since,)
    assert out == [{"sku": "SKU-2", "unit_cost": Decimal("4.00"),
                    "on_hand": 50, "updated_at": datetime(2026, 6, 2, tzinfo=timezone.utc)}]
