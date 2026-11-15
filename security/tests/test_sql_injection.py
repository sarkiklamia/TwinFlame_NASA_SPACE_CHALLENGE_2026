
"""SQL injection protection tests for TwinFlame backend."""

import duckdb

from app.backend.main import _quoted_identifier


def test_sql_identifier_escaping():
    malicious = 'fires"; DROP TABLE fires; --'
    escaped = _quoted_identifier(malicious)

    assert escaped == '"fires""; DROP TABLE fires; --"'


def test_parameterized_query_prevents_injection():
    con = duckdb.connect(":memory:")

    try:
        con.execute("CREATE TABLE fires (id VARCHAR)")
        con.execute("INSERT INTO fires VALUES (?)", ["fire_001"])

        malicious = "' OR 1=1 --"

        rows = con.execute(
            "SELECT id FROM fires WHERE id = ?",
            [malicious],
        ).fetchall()

        assert rows == []

        table_exists = con.execute(
            "SELECT COUNT(*) FROM fires"
        ).fetchone()[0]

        assert table_exists == 1

    finally:
        con.close()
