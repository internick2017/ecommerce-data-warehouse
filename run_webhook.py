"""Run the webhook receiver locally (uvicorn on 127.0.0.1:8000).

Bootstraps the schema, opens one DB connection, and serves create_app().
Expose publicly for a live demo with:  cloudflared tunnel --url http://localhost:8000
"""
import os

import uvicorn
from dotenv import load_dotenv

from load import pg_loader
from transform.runner import run_sql_files
from webhook.app import create_app

BOOTSTRAP_SQL = ["transform/sql/001_schemas.sql", "transform/sql/002_webhook_events.sql"]


def build():
    load_dotenv()
    conn = pg_loader.connect()
    run_sql_files(conn, BOOTSTRAP_SQL)
    secret = os.environ["SHOPIFY_WEBHOOK_SECRET"]
    return create_app(conn_factory=lambda: conn, secret=secret)


if __name__ == "__main__":
    uvicorn.run(build(), host="127.0.0.1", port=8000)
