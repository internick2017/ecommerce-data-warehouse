"""meta.webhook_events store: dedupe lookups + idempotent event recording."""


def event_seen(conn, event_id):
    """True if this Shopify webhook id was already recorded."""
    row = conn.execute(
        "select 1 from meta.webhook_events where event_id = %s", (event_id,)
    ).fetchone()
    return row is not None


def record_event(conn, event_id, topic, shopify_gid, hmac_valid, status):
    """Insert the event row. Idempotent: a repeated event_id is a no-op (first write wins)."""
    conn.execute(
        """
        insert into meta.webhook_events (event_id, topic, shopify_gid, hmac_valid, status)
        values (%s, %s, %s, %s, %s)
        on conflict (event_id) do nothing
        """,
        (event_id, topic, shopify_gid, hmac_valid, status),
    )
