"""Postgres raw-layer loader: audit rows, idempotent upserts, rejects, watermarks."""
import json
import os

import psycopg


def connect():
    return psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)


def start_load(conn):
    row = conn.execute(
        "insert into meta.load_audit default values returning load_id"
    ).fetchone()
    return row[0]


def finish_load(conn, load_id, status, rows_extracted=0, rows_loaded=0,
                rows_rejected=0, error=None):
    """status must be RUNNING/SUCCESS/FAILED (enforced by DB check constraint)."""
    conn.execute(
        """
        update meta.load_audit
        set finished_at = now(), status = %s, rows_extracted = %s,
            rows_loaded = %s, rows_rejected = %s, error = %s
        where load_id = %s
        """,
        (status, rows_extracted, rows_loaded, rows_rejected, error, load_id),
    )


def upsert_raw(conn, entity, records, load_id, extracted_at):
    """Idempotent batch upsert. extracted_at must be tz-aware. Atomic per call; safe to retry (last write wins)."""
    if entity not in ("orders", "products", "customers"):
        raise ValueError(f"unknown entity: {entity!r}")
    sql = f"""
        insert into raw.{entity} (shopify_gid, payload, load_id, extracted_at)
        values (%s, %s, %s, %s)
        on conflict (shopify_gid) do update
        set payload = excluded.payload,
            load_id = excluded.load_id,
            extracted_at = excluded.extracted_at,
            loaded_at = now()
    """
    with conn.transaction():
        with conn.cursor() as cur:
            cur.executemany(
                sql,
                [(r["id"], json.dumps(r), load_id, extracted_at) for r in records],
            )


def insert_reject(conn, entity, payload, reason, load_id):
    conn.execute(
        "insert into raw.rejects (entity, payload, reason, load_id) values (%s, %s, %s, %s)",
        (entity, json.dumps(payload), reason, load_id),
    )


def get_watermark(conn, entity):
    row = conn.execute(
        "select last_updated_at from meta.watermarks where entity = %s", (entity,)
    ).fetchone()
    return row[0] if row else None


def set_watermark(conn, entity, ts):
    conn.execute(
        """
        insert into meta.watermarks (entity, last_updated_at) values (%s, %s)
        on conflict (entity) do update set last_updated_at = excluded.last_updated_at
        """,
        (entity, ts),
    )
