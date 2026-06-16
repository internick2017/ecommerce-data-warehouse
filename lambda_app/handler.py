"""AWS Lambda entrypoint for the batch ELT pipeline.

Triggered on a schedule by EventBridge. Reuses pipeline.run_pipeline unchanged;
this module only wires environment config to a client + connection and returns
the run's status dict. An optional ``{"full": true}`` event forces a full
re-extract (ignores watermarks).
"""
import logging
import os

from extract.shopify_client import ShopifyClient
from load import pg_loader
from pipeline import run_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("lambda")


def handler(event, context):
    full = bool(event.get("full", False)) if isinstance(event, dict) else False
    client = ShopifyClient(
        shop_domain=os.environ["SHOPIFY_SHOP_DOMAIN"],
        access_token=os.environ["SHOPIFY_ACCESS_TOKEN"],
    )
    conn = pg_loader.connect()
    try:
        result = run_pipeline(conn, client, full=full)
        log.info("pipeline run complete: %s", result)
        return result
    finally:
        conn.close()
