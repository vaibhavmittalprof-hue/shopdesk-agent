import sqlite3
from pathlib import Path

# data/shopdesk.db, located relative to this file so it works from any folder
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "shopdesk.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    tier  TEXT NOT NULL CHECK (tier IN ('standard', 'vip'))
);

CREATE TABLE IF NOT EXISTS orders (
    id           INTEGER PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers(id),
    status       TEXT NOT NULL
                 CHECK (status IN ('placed', 'shipped', 'delivered', 'cancelled')),
    placed_at    TEXT NOT NULL,
    delivered_at TEXT,
    total_cents  INTEGER NOT NULL CHECK (total_cents >= 0)
);

CREATE TABLE IF NOT EXISTS order_items (
    id          INTEGER PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES orders(id),
    sku         TEXT NOT NULL,
    name        TEXT NOT NULL,
    quantity    INTEGER NOT NULL CHECK (quantity > 0),
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    category    TEXT NOT NULL
                CHECK (category IN ('electronics', 'clothing', 'home', 'gift_card'))
);

CREATE TABLE IF NOT EXISTS refunds (
    id              INTEGER PRIMARY KEY,
    order_id        INTEGER NOT NULL REFERENCES orders(id),
    amount_cents    INTEGER NOT NULL CHECK (amount_cents > 0),
    reason          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    summary     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  TEXT NOT NULL
);
"""


def get_connection(db_path=None):
    """Open a connection. Tests can pass a different path (a temp file)."""
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row          # rows behave like dicts: row["id"]
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite ignores foreign keys unless asked
    return conn


def init_db(conn):
    """Create the tables if they don't exist yet."""
    conn.executescript(SCHEMA)
    conn.commit()