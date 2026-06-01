import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "convrt.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT NOT NULL,
            phone     TEXT UNIQUE NOT NULL,
            email     TEXT,
            address   TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS products (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            description TEXT,
            category    TEXT,
            base_price  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS product_variants (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            size       TEXT NOT NULL,   -- pack size / count, e.g. "1kg", "60 caps"
            flavor     TEXT NOT NULL,   -- e.g. "Chocolate", "Unflavored"
            price      REAL NOT NULL,
            stock      INTEGER DEFAULT 0,
            FOREIGN KEY (product_id) REFERENCES products(id)
        );

        CREATE TABLE IF NOT EXISTS orders (
            id               TEXT PRIMARY KEY,
            customer_id      INTEGER NOT NULL,
            status           TEXT DEFAULT 'pending',
            total_amount     REAL NOT NULL,
            delivery_address TEXT,
            notes            TEXT,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );

        CREATE TABLE IF NOT EXISTS order_items (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id   TEXT NOT NULL,
            variant_id INTEGER NOT NULL,
            quantity   INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            FOREIGN KEY (order_id)   REFERENCES orders(id),
            FOREIGN KEY (variant_id) REFERENCES product_variants(id)
        );

        CREATE TABLE IF NOT EXISTS returns (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id   TEXT NOT NULL,
            reason     TEXT,
            status     TEXT DEFAULT 'requested',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(id)
        );

        CREATE TABLE IF NOT EXISTS waitlist (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            variant_id INTEGER NOT NULL,
            customer_id INTEGER NOT NULL,
            notified   INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (variant_id)  REFERENCES product_variants(id),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );

        CREATE TABLE IF NOT EXISTS escalations (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id  INTEGER,
            customer_phone TEXT,
            session_id   TEXT,
            issue        TEXT NOT NULL,
            status       TEXT DEFAULT 'pending',
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Human handoff: one row per live conversation
        CREATE TABLE IF NOT EXISTS conversations (
            session_id          TEXT PRIMARY KEY,
            customer_phone      TEXT,
            mode                TEXT DEFAULT 'ai',   -- 'ai' | 'human'
            needs_attention     INTEGER DEFAULT 0,   -- 1 = AI got stuck / escalated
            last_human_activity TIMESTAMP,
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Full transcript so staff can read + inject into any conversation
        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            role        TEXT NOT NULL,   -- 'customer' | 'ai' | 'staff'
            content     TEXT NOT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()


# ── Helpers ──────────────────────────────────────────────────────────────────

def row_to_dict(row) -> dict:
    return dict(row) if row else {}


def rows_to_list(rows) -> list[dict]:
    return [dict(r) for r in rows]
