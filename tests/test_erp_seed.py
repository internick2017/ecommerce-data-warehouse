import random
from decimal import Decimal

from erp.seed_erp import cost_rows_from_skus


def test_cost_rows_from_skus_deterministic_and_priced():
    pairs = [("SKU-1", Decimal("15.00")), ("SKU-2", Decimal("20.00"))]
    rng = random.Random(42)
    rows = cost_rows_from_skus(pairs, rng, cost_ratio=0.55)
    assert [r[0] for r in rows] == ["SKU-1", "SKU-2"]
    assert rows[0][1] == Decimal("8.25")
    assert rows[1][1] == Decimal("11.00")
    assert all(isinstance(r[2], int) and r[2] >= 0 for r in rows)
    assert cost_rows_from_skus(pairs, random.Random(42), cost_ratio=0.55) == rows
