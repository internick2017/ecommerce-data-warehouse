from unittest import mock

import lambda_app.handler as h


def _patch_deps(monkeypatch, run_result=None, run_side_effect=None):
    """Patch the handler's collaborators; return (recorded_calls, fake_conn)."""
    monkeypatch.setenv("SHOPIFY_SHOP_DOMAIN", "store.myshopify.com")
    monkeypatch.setenv("SHOPIFY_ACCESS_TOKEN", "shpat_test")
    fake_client = object()
    monkeypatch.setattr(h, "ShopifyClient", lambda **kwargs: fake_client)
    fake_conn = mock.Mock(name="conn")
    monkeypatch.setattr(h.pg_loader, "connect", lambda: fake_conn)

    calls = {}

    def fake_run(conn, client, full=False):
        calls["conn"] = conn
        calls["client"] = client
        calls["full"] = full
        if run_side_effect is not None:
            raise run_side_effect
        return run_result

    monkeypatch.setattr(h, "run_pipeline", fake_run)
    return calls, fake_conn, fake_client


def test_handler_returns_pipeline_status(monkeypatch):
    calls, fake_conn, fake_client = _patch_deps(
        monkeypatch, run_result={"status": "SUCCESS", "load_id": 7}
    )
    result = h.handler({}, None)
    assert result == {"status": "SUCCESS", "load_id": 7}
    assert calls["client"] is fake_client
    assert calls["full"] is False
    fake_conn.close.assert_called_once()


def test_handler_threads_full_flag(monkeypatch):
    calls, _, _ = _patch_deps(monkeypatch, run_result={"status": "SUCCESS"})
    h.handler({"full": True}, None)
    assert calls["full"] is True


def test_handler_handles_non_dict_event(monkeypatch):
    calls, _, _ = _patch_deps(monkeypatch, run_result={"status": "SUCCESS"})
    h.handler(None, None)
    assert calls["full"] is False


def test_handler_closes_connection_on_error(monkeypatch):
    calls, fake_conn, _ = _patch_deps(
        monkeypatch, run_side_effect=RuntimeError("boom")
    )
    import pytest
    with pytest.raises(RuntimeError):
        h.handler({}, None)
    fake_conn.close.assert_called_once()
