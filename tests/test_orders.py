from shopdesk.tools.orders import get_order, list_customer_orders


# ---------- get_order ----------

def test_get_order_found(conn):
    result = get_order({"order_id": 1001}, conn=conn)
    assert result["ok"] is True
    data = result["data"]
    assert data["order_id"] == 1001
    assert data["status"] == "delivered"
    assert data["total_cents"] == 5000
    assert data["refunded_cents"] == 0
    assert len(data["items"]) == 1
    assert data["items"][0]["category"] == "clothing"


def test_get_order_shows_existing_refund(conn):
    data = get_order({"order_id": 1008}, conn=conn)["data"]
    assert data["refunded_cents"] == 6000


def test_get_order_not_found_returns_structured_error(conn):
    result = get_order({"order_id": 9999}, conn=conn)
    assert result["ok"] is False
    assert result["error"]["code"] == "ORDER_NOT_FOUND"
    assert "hint" in result["error"]


def test_get_order_accepts_numeric_string(conn):
    # Models sometimes send "1001" instead of 1001; that is harmless and should work.
    assert get_order({"order_id": "1001"}, conn=conn)["ok"] is True


def test_get_order_rejects_bad_input_without_raising(conn):
    for bad in [{}, {"order_id": "abc"}, {"order_id": -5}, {"order_id": 0},
                {"order_id": 1001, "extra": "x"}, {"order_id": 10.5}]:
        result = get_order(bad, conn=conn)
        assert result["ok"] is False, bad
        assert result["error"]["code"] == "INVALID_INPUT", bad


# ---------- list_customer_orders ----------

def test_list_customer_orders_newest_first(conn):
    result = list_customer_orders({"customer_id": 2, "limit": 20}, conn=conn)
    assert result["ok"] is True
    orders = result["data"]["orders"]
    assert 1001 in [o["order_id"] for o in orders]
    dates = [o["placed_at"] for o in orders]
    assert dates == sorted(dates, reverse=True)


def test_list_customer_orders_respects_limit(conn):
    orders = list_customer_orders({"customer_id": 2, "limit": 1}, conn=conn)["data"]["orders"]
    assert len(orders) == 1


def test_list_customer_orders_default_limit(conn):
    orders = list_customer_orders({"customer_id": 2}, conn=conn)["data"]["orders"]
    assert len(orders) <= 5


def test_list_customer_orders_unknown_customer(conn):
    result = list_customer_orders({"customer_id": 9999}, conn=conn)
    assert result["ok"] is False
    assert result["error"]["code"] == "CUSTOMER_NOT_FOUND"


def test_list_customer_orders_customer_with_no_orders(conn):
    conn.execute(
        "INSERT INTO customers (id, name, email, tier) VALUES (99, 'No Orders', 'no@example.com', 'standard')"
    )
    conn.commit()
    result = list_customer_orders({"customer_id": 99}, conn=conn)
    assert result["ok"] is True
    assert result["data"]["orders"] == []


def test_list_customer_orders_rejects_bad_limits(conn):
    for bad_limit in [0, 21, -1, "many"]:
        result = list_customer_orders({"customer_id": 2, "limit": bad_limit}, conn=conn)
        assert result["ok"] is False, bad_limit
        assert result["error"]["code"] == "INVALID_INPUT"