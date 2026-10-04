from data.seed import REFERENCE_NOW, iso


def test_no_delivery_date_is_in_the_future(conn):
    future = conn.execute(
        "SELECT id FROM orders WHERE delivered_at > ?", (iso(REFERENCE_NOW),)
    ).fetchall()
    assert future == []


def test_order_totals_match_their_items(conn):
    rows = conn.execute(
        "SELECT o.id, o.total_cents, SUM(i.quantity * i.price_cents) AS item_total "
        "FROM orders o JOIN order_items i ON i.order_id = o.id GROUP BY o.id"
    ).fetchall()
    assert len(rows) == 100
    for row in rows:
        assert row["total_cents"] == row["item_total"], f"order {row['id']}"


def test_special_orders_exist(conn):
    ids = {r["id"] for r in conn.execute("SELECT id FROM orders WHERE id BETWEEN 1001 AND 1010")}
    assert ids == set(range(1001, 1011))


def test_database_rejects_duplicate_idempotency_key(conn):
    import sqlite3
    import pytest

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO refunds (order_id, amount_cents, reason, created_at, idempotency_key) "
            "VALUES (1001, 100, 'x', 'now', 'seed-refund-1008')"
        )