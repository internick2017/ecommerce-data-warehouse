from erp.odbc import build_conn_str


def test_build_conn_str_contains_all_parts():
    s = build_conn_str(
        server="localhost", port=1433, database="master",
        user="sa", password="P@ss",
    )
    assert "DRIVER={ODBC Driver 18 for SQL Server}" in s
    assert "SERVER=localhost,1433" in s
    assert "DATABASE=master" in s
    assert "UID=sa" in s
    assert "PWD=P@ss" in s
    assert "Encrypt=yes" in s
    assert "TrustServerCertificate=yes" in s


def test_build_conn_str_custom_driver():
    s = build_conn_str(
        server="h", port=1433, database="d", user="u", password="p",
        driver="ODBC Driver 17 for SQL Server",
    )
    assert "DRIVER={ODBC Driver 17 for SQL Server}" in s
