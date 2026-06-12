from datetime import datetime, timezone

from seed_shopify import spread_dates


def test_spread_dates_deterministic_and_in_range():
    now = datetime(2026, 6, 12, tzinfo=timezone.utc)
    dates = spread_dates(n=50, days_back=90, now=now, seed=42)
    assert len(dates) == 50
    assert dates == spread_dates(n=50, days_back=90, now=now, seed=42)
    for d in dates:
        assert (now - d).days <= 90
        assert d <= now
    assert dates == sorted(dates)
