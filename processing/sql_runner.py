
from __future__ import annotations

from pathlib import Path
import duckdb


class SQLRunner:
    def __init__(self, database_path: str = ":memory:"):
        self.connection = duckdb.connect(database_path)

    def execute_file(self, sql_file: str | Path):
        sql_file = Path(sql_file)

        if not sql_file.exists():
            raise FileNotFoundError(sql_file)

        sql = sql_file.read_text(encoding="utf-8")
        return self.connection.execute(sql)

    def execute(self, sql: str):
        return self.connection.execute(sql)

    def register_dataframe(self, name: str, dataframe):
        self.connection.register(name, dataframe)

    def fetch_dataframe(self, query: str):
        return self.connection.execute(query).fetchdf()

    def close(self):
        self.connection.close()
