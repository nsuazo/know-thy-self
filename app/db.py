"""SQLite connection handling and a minimal migration runner (PRAGMA user_version)."""
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import settings

log = logging.getLogger(__name__)
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def connect() -> sqlite3.Connection:
    # isolation_level=None: autocommit; multi-statement writes use tx().
    conn = sqlite3.connect(settings.db_path, timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


@contextmanager
def tx(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def init_db() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = int(path.name.split("_", 1)[0])
            if version <= current:
                continue
            log.info("Applying migration %s", path.name)
            conn.executescript(
                "BEGIN;\n" + path.read_text() + f"\nPRAGMA user_version = {version};\nCOMMIT;"
            )
    finally:
        conn.close()


def get_db():
    """FastAPI dependency: one connection per request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
