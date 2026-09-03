"""Utility script to initialize and explore the DuckDB database at Shared/Data/memory.duckdb."""

from pathlib import Path
import duckdb

# Database path definition
DB_DIR = Path(__file__).resolve().parent.parent / "Shared" / "Data"
DB_PATH = DB_DIR / "memory.duckdb"


def init_db() -> duckdb.DuckDBPyConnection:
    """Initialize or connect to the memory.duckdb database."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(DB_PATH))
    print(f"[+] Connected to DuckDB database at: {DB_PATH}")
    return conn


def create_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create initial tables for pattern memory and metadata."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key VARCHAR PRIMARY KEY,
            value VARCHAR,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO metadata (key, value)
        VALUES ('initialized', 'true'), ('project', 'ta-patterns-book');
    """
    )
    print("[+] Verified schema in 'memory.duckdb'.")


def explore_db(conn: duckdb.DuckDBPyConnection) -> None:
    """List tables and show basic statistics."""
    tables = conn.execute("SHOW TABLES;").fetchall()
    print(f"\n[=] Tables in database ({len(tables)} total):")
    for table in tables:
        t_name = table[0]
        count = conn.execute(f"SELECT COUNT(*) FROM {t_name};").fetchone()[0]
        print(f"  - {t_name}: {count} row(s)")


def main():
    conn = init_db()
    create_schema(conn)
    explore_db(conn)
    conn.close()
    print("[+] Database connection closed successfully.")


if __name__ == "__main__":
    main()
