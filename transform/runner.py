"""Executes .sql files statement by statement (split on ';').

Convention: SQL files in transform/sql/ contain one statement per ';' and
no semicolons inside string literals.
"""
from pathlib import Path


def run_sql_file(conn, path):
    text = Path(path).read_text(encoding="utf-8")
    for statement in text.split(";"):
        statement = statement.strip()
        if statement:
            conn.execute(statement)


def run_sql_files(conn, paths):
    for path in paths:
        run_sql_file(conn, path)
