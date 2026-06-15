"""Run one incremental ERP cost/inventory sync (pyodbc -> raw.erp_costs).

Needs the ODBC Driver 18 installed and the SQL Server container running
(docker compose up -d mssql). Refresh the curated margin afterwards with:
    python pipeline.py
"""
import os

from dotenv import load_dotenv

from erp import odbc, sync
from load import pg_loader
from transform.runner import run_sql_files


def main():
    load_dotenv()
    pg = pg_loader.connect()
    run_sql_files(pg, ["transform/sql/001_schemas.sql"])  # ensure raw.erp_costs exists

    erp_conn = odbc.connect(odbc.build_conn_str(
        server=os.environ.get("MSSQL_HOST", "localhost"),
        port=int(os.environ.get("MSSQL_PORT", "1433")),
        database=os.environ.get("MSSQL_DB", "master"),
        user=os.environ.get("MSSQL_USER", "sa"),
        password=os.environ["MSSQL_SA_PASSWORD"],
        driver=os.environ.get("MSSQL_ODBC_DRIVER", odbc.DEFAULT_DRIVER),
    ))
    result = sync.sync_costs(pg, erp_conn.cursor())
    print(f"ERP sync: rows_synced={result['rows_synced']} "
          f"watermark={result['new_watermark']}")


if __name__ == "__main__":
    main()
