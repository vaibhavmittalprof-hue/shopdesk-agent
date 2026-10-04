import random
from datetime import datetime, timedelta
from pathlib import Path

from shopdesk.db import DB_PATH, get_connection, init_db

# A FIXED "today", so the data (and later your tests and evals) never change.
REFERENCE_NOW = datetime(2026, 10, 1, 12, 0, 0)

FIRST_NAMES = ["Asha", "Ben", "Chen", "Dina", "Eli", "Farah", "Gus", "Hana",
               "Ivan", "Jia", "Kofi", "Lena", "Mateo", "Nia", "Omar"]
LAST_NAMES = ["Patel", "Smith", "Wong", "Garcia", "Khan", "Silva", "Novak", "Okafor"]

VIP_IDS = {1, 11, 21}


def iso(dt):
    return dt.isoformat(timespec="seconds")


def days_ago(n):
    return REFERENCE_NOW - timedelta(days=n)


# Hand-built orders with KNOWN ids, so tests and evals can refer to them.
# (order_id, customer_id, status, placed_days_ago, delivered_days_ago, items)
# item = (sku, name, quantity, price_cents, category)
SPECIAL_ORDERS = [
    (1001, 2, "delivered", 6, 3, [("TS-100", "Cotton T-Shirt", 1, 5000, "clothing")]),
    (1002, 3, "delivered", 23, 20, [("HP-200", "Wireless Headphones", 1, 80000, "electronics")]),
    (1003, 4, "delivered", 48, 45, [("JK-300", "Rain Jacket", 1, 12000, "clothing")]),
    (1004, 5, "delivered", 203, 200, [("BL-400", "Blender", 1, 9000, "home")]),
    (1005, 6, "cancelled", 10, None, [("SH-500", "Running Shoes", 1, 7000, "clothing")]),
    (1006, 7, "shipped", 2, None, [("MS-600", "Gaming Mouse", 1, 4500, "electronics")]),
    (1007, 8, "delivered", 8, 5, [("GC-700", "Gift Card 50", 1, 5000, "gift_card")]),
    (1008, 9, "delivered", 15, 12, [("HD-101", "Hoodie", 1, 6000, "clothing")]),     # fully refunded
    (1009, 10, "delivered", 15, 12, [("JN-102", "Jeans", 2, 4000, "clothing")]),     # partly refunded
    # VIP customer, high value, delivered 18 days ago: outside the standard
    # 14-day electronics window but inside the VIP 21-day window
    (1010, 1, "delivered", 21, 18, [("LP-800", "Laptop", 1, 250000, "electronics")]),
]

# (order_id, amount_cents, reason, idempotency_key)
SPECIAL_REFUNDS = [
    (1008, 6000, "Wrong size", "seed-refund-1008"),   # the whole order
    (1009, 3000, "One pair damaged", "seed-refund-1009"),  # 3000 of 8000
]


def insert_order(conn, order_id, customer_id, status, placed_days, delivered_days, items):
    total = sum(qty * price for _, _, qty, price, _ in items)
    delivered_at = iso(days_ago(delivered_days)) if delivered_days is not None else None
    conn.execute(
        "INSERT INTO orders (id, customer_id, status, placed_at, delivered_at, total_cents) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (order_id, customer_id, status, iso(days_ago(placed_days)), delivered_at, total),
    )
    for sku, name, qty, price, category in items:
        conn.execute(
            "INSERT INTO order_items (order_id, sku, name, quantity, price_cents, category) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (order_id, sku, name, qty, price, category),
        )


def main(db_path=None, verbose=True):
    """Build the fake shop database. Tests pass a temporary db_path."""
    path = Path(db_path) if db_path else DB_PATH
    path.unlink(missing_ok=True)         # start fresh every time
    conn = get_connection(path)
    init_db(conn)
    rng = random.Random(42)              # fixed seed = same "random" data every run

    # 30 customers
    for cid in range(1, 31):
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        conn.execute(
            "INSERT INTO customers (id, name, email, tier) VALUES (?, ?, ?, ?)",
            (cid, f"{first} {last}", f"{first}.{last}{cid}@example.com".lower(),
             "vip" if cid in VIP_IDS else "standard"),
        )

    # The hand-built orders and refunds
    for order in SPECIAL_ORDERS:
        insert_order(conn, *order)
    for order_id, amount, reason, key in SPECIAL_REFUNDS:
        conn.execute(
            "INSERT INTO refunds (order_id, amount_cents, reason, created_at, idempotency_key) "
            "VALUES (?, ?, ?, ?, ?)",
            (order_id, amount, reason, iso(days_ago(10)), key),
        )

    # 90 random orders, ids 1011-1100
    catalog = [
        ("clothing", "Sweater", 4000, 12000),
        ("electronics", "Tablet", 20000, 90000),
        ("home", "Lamp", 3000, 15000),
    ]
    for order_id in range(1011, 1101):
        category, name, low, high = rng.choice(catalog)
        price = rng.randrange(low, high, 100)
        status = rng.choices(
            ["delivered", "shipped", "placed", "cancelled"], weights=[70, 15, 10, 5]
        )[0]
        placed = rng.randint(4, 240)     # at least 4 days ago, so delivery is never in the future
        delivered = placed - 3 if status == "delivered" else None
        insert_order(
            conn, order_id, rng.randint(1, 30), status, placed, delivered,
            [(f"RND-{order_id}", name, 1, price, category)],
        )

    conn.commit()

    if verbose:
        for table in ["customers", "orders", "order_items", "refunds", "tickets"]:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"{table}: {count} rows")
    conn.close()


if __name__ == "__main__":
    main()