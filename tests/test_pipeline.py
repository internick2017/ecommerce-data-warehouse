from datetime import datetime, timezone

from load.raw_writer import LocalRawWriter
from pipeline import run_pipeline
from tests import fixtures


def fake_extract_factory(data):
    """data: {entity: [records]} — mimics extract_entity(client, entity, updated_since)."""
    calls = []

    def fake_extract(client, entity, updated_since=None):
        calls.append((entity, updated_since))
        yield from data.get(entity, [])

    fake_extract.calls = calls
    return fake_extract


def seed_data():
    return {
        "products": [fixtures.product(1, "Mug"), fixtures.product(2, "Tee")],
        "customers": [fixtures.customer(1, "Ana"), fixtures.customer(2, "Luis")],
        "orders": [
            fixtures.order(1, "gid://shopify/Customer/1", "30.00",
                           [fixtures.item(1, "gid://shopify/Product/1", 2, "15.00")]),
        ],
    }


def test_pipeline_end_to_end(db, tmp_path):
    extract = fake_extract_factory(seed_data())
    result = run_pipeline(conn=db, client=None, extract_fn=extract,
                          writer=LocalRawWriter(tmp_path))
    assert result["status"] == "SUCCESS"
    assert db.execute("select count(*) from curated.fact_orders").fetchone()[0] == 1
    status = db.execute(
        "select status from meta.load_audit where load_id=%s", (result["load_id"],)
    ).fetchone()[0]
    assert status == "SUCCESS"
    # watermarks advanced
    wm = db.execute("select count(*) from meta.watermarks").fetchone()[0]
    assert wm == 3


def test_pipeline_routes_invalid_records_to_rejects(db, tmp_path):
    data = seed_data()
    data["orders"].append({"id": "gid://shopify/Order/99"})  # invalid: missing fields
    extract = fake_extract_factory(data)
    result = run_pipeline(conn=db, client=None, extract_fn=extract,
                          writer=LocalRawWriter(tmp_path))
    assert result["status"] == "SUCCESS"
    assert result["rows_rejected"] == 1
    reason = db.execute("select reason from raw.rejects").fetchone()[0]
    assert reason


def test_second_run_uses_watermarks(db, tmp_path):
    extract = fake_extract_factory(seed_data())
    run_pipeline(conn=db, client=None, extract_fn=extract, writer=LocalRawWriter(tmp_path))
    extract2 = fake_extract_factory(seed_data())
    run_pipeline(conn=db, client=None, extract_fn=extract2, writer=LocalRawWriter(tmp_path))
    assert all(since is not None for _, since in extract2.calls)


def test_full_flag_ignores_watermarks(db, tmp_path):
    extract = fake_extract_factory(seed_data())
    run_pipeline(conn=db, client=None, extract_fn=extract, writer=LocalRawWriter(tmp_path))
    extract2 = fake_extract_factory(seed_data())
    run_pipeline(conn=db, client=None, extract_fn=extract2,
                 writer=LocalRawWriter(tmp_path), full=True)
    assert all(since is None for _, since in extract2.calls)


def test_duplicate_gid_in_extraction_deduped(db, tmp_path):
    data = seed_data()
    data["orders"].append(dict(data["orders"][0]))  # same GID twice
    extract = fake_extract_factory(data)
    result = run_pipeline(conn=db, client=None, extract_fn=extract,
                          writer=LocalRawWriter(tmp_path))
    assert result["status"] == "SUCCESS"
    assert db.execute("select count(*) from raw.orders").fetchone()[0] == 1


def test_failure_marks_audit_failed_and_keeps_watermarks(db, tmp_path):
    extract = fake_extract_factory(seed_data())
    run_pipeline(conn=db, client=None, extract_fn=extract, writer=LocalRawWriter(tmp_path))
    wm_before = db.execute(
        "select last_updated_at from meta.watermarks where entity='orders'"
    ).fetchone()[0]

    def exploding_extract(client, entity, updated_since=None):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    import pytest
    with pytest.raises(RuntimeError):
        run_pipeline(conn=db, client=None, extract_fn=exploding_extract,
                     writer=LocalRawWriter(tmp_path))
    last_status = db.execute(
        "select status from meta.load_audit order by load_id desc limit 1"
    ).fetchone()[0]
    assert last_status == "FAILED"
    wm_after = db.execute(
        "select last_updated_at from meta.watermarks where entity='orders'"
    ).fetchone()[0]
    assert wm_after == wm_before
