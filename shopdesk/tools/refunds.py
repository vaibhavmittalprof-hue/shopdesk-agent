from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from shopdesk.clock import current_time
from shopdesk.policy import APPROVAL_LIMIT_CENTS, window_days
from shopdesk.tools.common import err, ok, parse_args, use_connection


def dollars(cents: int) -> str:
    """5000 -> '$50.00' (for messages only; we never store money as text)."""
    return f"${cents // 100}.{cents % 100:02d}"


# =====================================================================
# check_refund_eligibility  (read-only)
# =====================================================================

class CheckRefundEligibilityArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: int = Field(..., gt=0, description="Numeric order ID, for example 1001.")


CHECK_REFUND_ELIGIBILITY_SPEC = {
    "name": "check_refund_eligibility",
    "description": (
        "Check whether ONE order can be refunded under the refund policy. Returns "
        "eligible (true/false), a reason_code, a plain-English message, and "
        "refundable_cents (the most that can be refunded right now; 0 if not "
        "eligible). Money is in cents. Use this whenever a customer asks for a "
        "refund, and always before any refund is issued. This only reads data; "
        "it never changes anything."
    ),
    "input_schema": CheckRefundEligibilityArgs.model_json_schema(),
}


def _answer(order_id, eligible, reason_code, message,
            refundable_cents=0, days=None, window=None, needs_approval=False):
    """Build the standard 'here is my decision' result."""
    return ok(
        {
            "order_id": order_id,
            "eligible": eligible,
            "reason_code": reason_code,
            "message": message,
            "refundable_cents": refundable_cents,
            "days_since_delivery": days,
            "window_days": window,
            "full_refund_needs_approval": needs_approval,
        }
    )


def check_refund_eligibility(raw_args: dict, conn=None, now=None) -> dict:
    args, error = parse_args(CheckRefundEligibilityArgs, raw_args)
    if error:
        return error
    now = now or current_time()          # tests can pass their own "now"

    # ---- 1. Gather the facts ----
    with use_connection(conn) as db:
        order = db.execute(
            "SELECT o.id, o.status, o.delivered_at, o.total_cents, c.tier "
            "FROM orders o JOIN customers c ON c.id = o.customer_id "
            "WHERE o.id = ?",
            (args.order_id,),
        ).fetchone()
        if order is None:
            return err(
                "ORDER_NOT_FOUND",
                f"No order with id {args.order_id}.",
                "Order IDs are numbers like 1001. Ask the customer to confirm the order number.",
            )
        categories = [
            row["category"]
            for row in db.execute(
                "SELECT category FROM order_items WHERE order_id = ?", (args.order_id,)
            )
        ]
        refunded = db.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) FROM refunds WHERE order_id = ?",
            (args.order_id,),
        ).fetchone()[0]

    order_id, tier = order["id"], order["tier"]

    # ---- 2. Apply the rules, in order. The first rule that fails decides. ----
    if order["status"] == "cancelled":
        return _answer(order_id, False, "ORDER_CANCELLED",
                       f"Order {order_id} was cancelled, so the customer was never charged "
                       "and there is nothing to refund.")

    if order["status"] != "delivered":
        return _answer(order_id, False, "NOT_DELIVERED",
                       f"Order {order_id} has not been delivered yet (status: {order['status']}). "
                       "Refunds are only possible after delivery.")

    if not categories or order["delivered_at"] is None:
        return err("DATA_PROBLEM", f"Order {order_id} has incomplete records.",
                   "Do not guess. Escalate this order to a human agent.")

    blocked = sorted({c for c in categories if window_days(c, tier) is None})
    if blocked:
        return _answer(order_id, False, "NON_REFUNDABLE_ITEM",
                       f"Order {order_id} contains non-refundable item type(s): {', '.join(blocked)}.")

    remaining = order["total_cents"] - refunded
    if remaining <= 0:
        return _answer(order_id, False, "ALREADY_REFUNDED",
                       f"Order {order_id} has already been fully refunded.")

    days = (now - datetime.fromisoformat(order["delivered_at"])).days   # whole days
    window = min(window_days(c, tier) for c in categories)              # shortest window wins
    if days > window:
        return _answer(order_id, False, "WINDOW_EXPIRED",
                       f"Order {order_id} was delivered {days} days ago, but the refund "
                       f"window for this order is {window} days.",
                       days=days, window=window)

    return _answer(order_id, True, "ELIGIBLE",
                   f"Order {order_id} is eligible for a refund of up to {dollars(remaining)} "
                   f"(delivered {days} days ago, window is {window} days).",
                   refundable_cents=remaining, days=days, window=window,
                   needs_approval=order["total_cents"] > APPROVAL_LIMIT_CENTS)


# =====================================================================
# issue_refund  (WRITES data: moves money)
# =====================================================================

class IssueRefundArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    order_id: int = Field(..., gt=0, description="Numeric order ID, for example 1001.")
    amount_cents: int = Field(
        ..., gt=0,
        description="Refund amount in CENTS (5000 = $50.00). Never more than refundable_cents "
                    "from check_refund_eligibility.",
    )
    reason: str = Field(
        ..., min_length=3, max_length=200,
        description="Short reason for the refund, in the customer's words.",
    )
    idempotency_key: str = Field(
        ..., min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$",
        description="A unique key for THIS refund request, for example refund-1001-a7f3c2. "
                    "If a call fails or times out and you retry the SAME refund, reuse the SAME "
                    "key. Use a NEW key only for a genuinely new refund.",
    )


ISSUE_REFUND_SPEC = {
    "name": "issue_refund",
    "description": (
        "Issue a refund for ONE order. This CHANGES data and moves money, so only call it "
        "after check_refund_eligibility says the order is eligible AND the customer has "
        "clearly asked for the refund AND confirmed the exact amount. Money is in cents. "
        "If the total refunded on the order would go above $200.00 it is refused with "
        "APPROVAL_REQUIRED; hand those to a human with escalate_to_human."
    ),
    "input_schema": IssueRefundArgs.model_json_schema(),
}


def _refund_payload(db, row, already_processed: bool) -> dict:
    total = db.execute(
        "SELECT total_cents FROM orders WHERE id = ?", (row["order_id"],)
    ).fetchone()[0]
    refunded = db.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) FROM refunds WHERE order_id = ?",
        (row["order_id"],),
    ).fetchone()[0]
    return {
        "refund_id": row["id"],
        "order_id": row["order_id"],
        "amount_cents": row["amount_cents"],
        "reason": row["reason"],
        "created_at": row["created_at"],
        "idempotency_key": row["idempotency_key"],
        "order_remaining_cents": total - refunded,
        "already_processed": already_processed,
    }


def _issue(db, args, now) -> dict:
    # ---- 1. Is this a RETRY of a refund we already made? (checked FIRST on purpose) ----
    existing = db.execute(
        "SELECT id, order_id, amount_cents, reason, created_at, idempotency_key "
        "FROM refunds WHERE idempotency_key = ?",
        (args.idempotency_key,),
    ).fetchone()
    if existing is not None:
        if existing["order_id"] == args.order_id and existing["amount_cents"] == args.amount_cents:
            return ok(_refund_payload(db, existing, already_processed=True))
        return err(
            "IDEMPOTENCY_KEY_REUSED",
            "This idempotency_key was already used for a different refund.",
            "Use a new, unique idempotency_key for a new refund. Never reuse a key for a different refund.",
        )

    # ---- 2. Is this refund allowed by the policy? ----
    check = check_refund_eligibility({"order_id": args.order_id}, conn=db, now=now)
    if not check["ok"]:
        return check
    facts = check["data"]
    if not facts["eligible"]:
        return err(
            "NOT_ELIGIBLE",
            f"Refund refused ({facts['reason_code']}): {facts['message']}",
            "Do not retry. Explain the reason to the customer.",
        )
    if args.amount_cents > facts["refundable_cents"]:
        return err(
            "AMOUNT_TOO_HIGH",
            f"Requested {dollars(args.amount_cents)} but at most "
            f"{dollars(facts['refundable_cents'])} can be refunded for this order.",
            "Ask the customer to confirm a smaller amount.",
        )

    # ---- 3. Does it need a human? The limit applies to the TOTAL refunded on the order,
    #         so splitting one big refund into several small ones cannot get around it. ----
    already_refunded = db.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) FROM refunds WHERE order_id = ?",
        (args.order_id,),
    ).fetchone()[0]
    if already_refunded + args.amount_cents > APPROVAL_LIMIT_CENTS:
        return err(
            "APPROVAL_REQUIRED",
            f"Refunds above {dollars(APPROVAL_LIMIT_CENTS)} in total on one order need human approval.",
            "Do not retry and do not try other amounts. Call escalate_to_human with reason "
            "REFUND_NEEDS_APPROVAL and tell the customer a human agent will follow up.",
        )

    # ---- 4. All checks passed: record the refund ----
    cursor = db.execute(
        "INSERT INTO refunds (order_id, amount_cents, reason, created_at, idempotency_key) "
        "VALUES (?, ?, ?, ?, ?)",
        (args.order_id, args.amount_cents, args.reason,
         now.isoformat(timespec="seconds"), args.idempotency_key),
    )
    row = db.execute(
        "SELECT id, order_id, amount_cents, reason, created_at, idempotency_key "
        "FROM refunds WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return ok(_refund_payload(db, row, already_processed=False))


def issue_refund(raw_args: dict, conn=None, now=None) -> dict:
    args, error = parse_args(IssueRefundArgs, raw_args)
    if error:
        return error
    now = now or current_time()

    with use_connection(conn) as db:
        # Lock the database for writing, so "check, then insert" cannot be interleaved
        # with another refund. Assumes no transaction is already open on this connection.
        db.execute("BEGIN IMMEDIATE")
        try:
            result = _issue(db, args, now)
        except Exception:
            db.rollback()
            raise
        if result["ok"] and not result["data"]["already_processed"]:
            db.commit()          # a new refund: save it
        else:
            db.rollback()        # nothing to save: release the lock
        return result


