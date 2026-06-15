"""SQL Server ODBC connection helpers. build_conn_str is pure; connect() is the
only place that touches pyodbc (imported lazily so this module imports without
the driver present)."""

DEFAULT_DRIVER = "ODBC Driver 18 for SQL Server"


def build_conn_str(server, port, database, user, password, driver=DEFAULT_DRIVER):
    """Build a SQL Server ODBC connection string.

    Encrypt=yes + TrustServerCertificate=yes accepts the dev container's
    self-signed cert (Driver 18 encrypts by default and would otherwise reject it).
    """
    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={server},{port};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=yes"
    )


def connect(conn_str):
    """Open a pyodbc connection. Requires the ODBC driver to be installed."""
    import pyodbc
    return pyodbc.connect(conn_str)
