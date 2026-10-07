from shopdesk.tools.refunds import issue_refund
from shopdesk.tools.tickets import escalate_to_human


def refund_count(conn):
    return conn.execute("SELECT COUNT(*) FROM refunds").fetchone()[0]


def args(order_id=1001, amount=5000, key="refund-1001-aaaa1111", reason="Changed my mind"):
    return {"order_id": order_id, "amount_cents": amount, "reason": reason, "idempotency_key": key}


# ---------- the happy path ----------

def test_full_refund_succeeds_and_is_recorded(conn):
    before = refund_count(conn)
    result = issue_refund(args(), conn=conn)
    assert result["ok"] is True
    data = result["data"]
    assert data["amount_cents"] == 5000
    assert data["already_processed"] is False
    assert data["order_remaining_cents"] == 0
    assert refund_count(conn) == before + 1


def test_partial_refund_leaves_the_balance(conn):
    data = issue_refund(args(1009, 2000, "refund-1009-bbbb2222"), conn=conn)["data"]
    assert data["order_remaining_cents"] == 3000          # 8000 - 3000 earlier - 2000 now


def test_refund_uses_the_shop_clock(conn):
    data = issue_refund(args(), conn=conn)["data"]
    assert data["created_at"] == "2026-10-01T12:00:00"


# ---------- idempotency: the double-refund protection ----------

def test_same_key_twice_makes_only_one_refund(conn):
    first = issue_refund(args(), conn=conn)
    before = refund_count(conn)
    second = issue_refund(args(), conn=conn)
    assert second["ok"] is True
    assert second["data"]["already_processed"] is True
    assert second["data"]["refund_id"] == first["data"]["refund_id"]
    assert refund_count(conn) == before                    # no second row


def test_retry_still_succeeds_after_the_order_is_fully_refunded(conn):
    issue_refund(args(), conn=conn)                        # now the order is fully refunded
    retry = issue_refund(args(), conn=conn)                # same key: must NOT say "already refunded"
    assert retry["ok"] is True and retry["data"]["already_processed"] is True


def test_reusing_a_key_for_a_different_refund_is_rejected(conn):
    issue_refund(args(1009, 2000, "refund-shared-key-1"), conn=conn)
    before = refund_count(conn)
    result = issue_refund(args(1009, 2500, "refund-shared-key-1"), conn=conn)
    assert result["ok"] is False
    assert result["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert refund_count(conn) == before


def test_a_new_key_cannot_refund_an_already_refunded_order(conn):
    issue_refund(args(), conn=conn)
    result = issue_refund(args(key="refund-1001-different"), conn=conn)
    assert result["ok"] is False
    assert result["error"]["code"] == "NOT_ELIGIBLE"
    assert "ALREADY_REFUNDED" in result["error"]["message"]


# ---------- amounts ----------

def test_amount_above_what_is_refundable_is_rejected(conn):
    before = refund_count(conn)
    result = issue_refund(args(amount=5001), conn=conn)
    assert result["error"]["code"] == "AMOUNT_TOO_HIGH"
    assert refund_count(conn) == before


def test_two_refunds_together_cannot_exceed_the_order(conn):
    assert issue_refund(args(1009, 3000, "refund-1009-first01"), conn=conn)["ok"] is True
    second = issue_refund(args(1009, 3000, "refund-1009-second2"), conn=conn)   # only 2000 left
    assert second["error"]["code"] == "AMOUNT_TOO_HIGH"


# ---------- policy ----------

def test_ineligible_orders_are_refused(conn):
    before = refund_count(conn)
    for order_id, reason_code in [(1002, "WINDOW_EXPIRED"), (1005, "ORDER_CANCELLED"),
                                  (1006, "NOT_DELIVERED"), (1007, "NON_REFUNDABLE_ITEM")]:
        result = issue_refund(args(order_id, 1000, f"refund-{order_id}-xxxxxxxx"), conn=conn)
        assert result["error"]["code"] == "NOT_ELIGIBLE", order_id
        assert reason_code in result["error"]["message"], order_id
    assert refund_count(conn) == before


def test_unknown_order(conn):
    result = issue_refund(args(9999, 1000, "refund-9999-xxxxxxxx"), conn=conn)
    assert result["error"]["code"] == "ORDER_NOT_FOUND"


# ---------- the $200 approval limit ----------

def test_exactly_at_the_limit_is_allowed(conn):
    result = issue_refund(args(1010, 20000, "refund-1010-limit001"), conn=conn)
    assert result["ok"] is True


def test_one_cent_over_the_limit_needs_approval(conn):
    before = refund_count(conn)
    result = issue_refund(args(1010, 20001, "refund-1010-limit002"), conn=conn)
    assert result["error"]["code"] == "APPROVAL_REQUIRED"
    assert "escalate_to_human" in result["error"]["hint"]
    assert refund_count(conn) == before


def test_big_refund_needs_approval(conn):
    assert issue_refund(args(1010, 250000, "refund-1010-whole001"), conn=conn)["error"]["code"] == "APPROVAL_REQUIRED"


def test_splitting_a_big_refund_cannot_bypass_the_limit(conn):
    assert issue_refund(args(1010, 20000, "refund-1010-split001"), conn=conn)["ok"] is True
    second = issue_refund(args(1010, 1, "refund-1010-split002"), conn=conn)     # total would be 20001
    assert second["error"]["code"] == "APPROVAL_REQUIRED"


# ---------- bad input and safety ----------

def test_bad_input_never_writes_or_raises(conn):
    before = refund_count(conn)
    bad_inputs = [
        {},
        args(amount=0),
        args(amount=-5),
        args(amount=10.5),
        args(key="short"),
        args(key="has spaces in it"),
        args(reason=""),
        args(reason="  "),
        {**args(), "extra": "x"},
    ]
    for bad in bad_inputs:
        result = issue_refund(bad, conn=conn)
        assert result["ok"] is False, bad
        assert result["error"]["code"] == "INVALID_INPUT", bad
    assert refund_count(conn) == before


def test_failures_do_not_leave_the_database_locked(conn):
    issue_refund(args(amount=999999), conn=conn)           # rejected
    assert conn.in_transaction is False
    assert issue_refund(args(), conn=conn)["ok"] is True   # and the next one still works
    assert conn.in_transaction is False


# ---------- escalate_to_human ----------

def test_escalate_creates_an_open_ticket(conn):
    result = escalate_to_human(
        {"reason": "REFUND_NEEDS_APPROVAL", "summary": "Customer wants a refund of $2,500 on order 1010."},
        conn=conn,
    )
    assert result["ok"] is True
    ticket = conn.execute("SELECT summary, status FROM tickets WHERE id = ?", (result["data"]["ticket_id"],)).fetchone()
    assert ticket["status"] == "open"
    assert "REFUND_NEEDS_APPROVAL" in ticket["summary"] and "order 1010" in ticket["summary"]


def test_escalate_rejects_bad_input(conn):
    for bad in [{}, {"reason": "BECAUSE", "summary": "A long enough summary here."},
                {"reason": "OTHER", "summary": "short"}, {"reason": "OTHER"}]:
        result = escalate_to_human(bad, conn=conn)
        assert result["ok"] is False and result["error"]["code"] == "INVALID_INPUT", bad
    assert conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 0