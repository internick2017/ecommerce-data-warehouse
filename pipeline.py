"""Batch ELT orchestrator: extract -> validate -> raw (S3 + Postgres) -> SQL transforms -> quality gates.

Usage:
    python pipeline.py            # incremental (per-entity updated_at watermarks)
    python pipeline.py --full     # ignore watermarks, full re-extract
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

from extract.extractor import extract_entity
from extract.shopify_client import ShopifyClient
from load import pg_loader
from load.models import validate_record
from load.raw_writer import writer_from_env
from transform.quality import run_quality_checks
from transform.runner import run_sql_files

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pipeline")

ENTITIES = ["products", "customers", "orders"]  # dims before facts
TRANSFORM_SQL = ["transform/sql/010_staging.sql", "transform/sql/020_curated.sql"]


def _parse_ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def run_pipeline(conn, client, extract_fn=extract_entity, writer=None, full=False):
    writer = writer or writer_from_env()
    run_sql_files(conn, ["transform/sql/001_schemas.sql"])
    load_id = pg_loader.start_load(conn)
    extracted = loaded = rejected = 0
    new_watermarks = {}
    try:
        for entity in ENTITIES:
            since = None if full else pg_loader.get_watermark(conn, entity)
            good, max_updated = [], None
            for record in extract_fn(client, entity, updated_since=since):
                extracted += 1
                ok, reason = validate_record(entity, record)
                if not ok:
                    rejected += 1
                    pg_loader.insert_reject(conn, entity, record, reason, load_id)
                    continue
                good.append(record)
                ts = _parse_ts(record["updatedAt"])
                if max_updated is None or ts > max_updated:
                    max_updated = ts
            uri = writer.write(entity, good, load_id)
            pg_loader.upsert_raw(conn, entity, good, load_id,
                                 extracted_at=datetime.now(timezone.utc))
            loaded += len(good)
            if max_updated:
                new_watermarks[entity] = max_updated
            log.info("%s: extracted=%d loaded=%d raw_file=%s",
                     entity, len(good), len(good), uri)

        run_sql_files(conn, TRANSFORM_SQL)
        run_quality_checks(conn)

        for entity, ts in new_watermarks.items():
            pg_loader.set_watermark(conn, entity, ts)
        pg_loader.finish_load(conn, load_id, "SUCCESS", extracted, loaded, rejected)
        log.info("load %d SUCCESS (extracted=%d loaded=%d rejected=%d)",
                 load_id, extracted, loaded, rejected)
        return {"status": "SUCCESS", "load_id": load_id,
                "rows_extracted": extracted, "rows_loaded": loaded,
                "rows_rejected": rejected}
    except Exception as exc:
        pg_loader.finish_load(conn, load_id, "FAILED", extracted, loaded,
                              rejected, error=str(exc))
        log.error("load %d FAILED: %s", load_id, exc)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="ignore watermarks")
    args = parser.parse_args()
    load_dotenv()
    client = ShopifyClient(
        shop_domain=os.environ["SHOPIFY_SHOP_DOMAIN"],
        access_token=os.environ["SHOPIFY_ACCESS_TOKEN"],
    )
    conn = pg_loader.connect()
    try:
        run_pipeline(conn, client, full=args.full)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
