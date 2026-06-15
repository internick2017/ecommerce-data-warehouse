from datetime import datetime, timezone
from decimal import Decimal

from transform.runner import run_sql_files
from erp import sync
from load import pg_loader

T1 = datetime(2026, 6, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 6, 2, tzinfo=timezone.utc)
T3 = datetime(2026, 6, 3, tzinfo=timezone.utc)


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def execute(self, sql, *params):
        self.executed.append((sql, params))
        return self

    def fetchall(self):
        return self._rows


def bootstrap(db):
    run_sql_files(db, ["transform/sql/001_schemas.sql"])


def test_first_sync_lands_rows_and_sets_watermark(db):
    bootstrap(db)
    cur = FakeCursor([
        ("SKU-1", Decimal("8.25"), 10, T1),
        ("SKU-2", Decimal("4.00"), 50, T2),
    ])
    result = sync.sync_costs(db, cur)
    assert result["rows_synced"] == 2
    assert db.execute("select count(*) from raw.erp_costs").fetchone()[0] == 2
    assert pg_loader.get_watermark(db, "erp_costs") == T2
    assert cur.executed[0][1] == ()


def test_second_sync_uses_watermark_and_applies_delta(db):
    bootstrap(db)
    sync.sync_costs(db, FakeCursor([
        ("SKU-1", Decimal("8.25"), 10, T1),
        ("SKU-2", Decimal("4.00"), 50, T2),
    ]))
    cur2 = FakeCursor([("SKU-1", Decimal("9.00"), 8, T3)])
    result = sync.sync_costs(db, cur2)
    assert result["rows_synced"] == 1
    assert cur2.executed[0][1] == (T2,)
    row = db.execute("select unit_cost, on_hand from raw.erp_costs where sku='SKU-1'").fetchone()
    assert row == (Decimal("9.00"), 8)
    assert db.execute("select count(*) from raw.erp_costs").fetchone()[0] == 2
    assert pg_loader.get_watermark(db, "erp_costs") == T3


def test_resync_same_data_is_idempotent(db):
    bootstrap(db)
    rows = [("SKU-1", Decimal("8.25"), 10, T1)]
    sync.sync_costs(db, FakeCursor(rows))
    sync.sync_costs(db, FakeCursor(rows))
    assert db.execute("select count(*) from raw.erp_costs").fetchone()[0] == 1


def test_empty_sync_keeps_watermark(db):
    bootstrap(db)
    result = sync.sync_costs(db, FakeCursor([]))
    assert result["rows_synced"] == 0
    assert pg_loader.get_watermark(db, "erp_costs") is None
