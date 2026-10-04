from pydantic import BaseModel, ConfigDict, Field

from shopdesk.tools.common import err, ok, parse_args, use_connection


# ---------- get_order ----------

class GetOrderArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")   # unknown arguments -> clear error

    order_id: int = Field(..., gt=0, description="Numeric order ID, for example 1001.")


GET_ORDER_SPEC = {
    "name": "get_order",
    "description": (
        "Look up ONE order by its numeric order ID. Returns the order status, dates, "
        "total, the amount already refunded, and the items. All money amounts are in "
        "cents (5000 means $50.00). Use this when the customer mentions a specific "
        "order number. This only reads data; it never changes anything."
    ),
    "input_schema": GetOrderArgs.model_json_schema(),
}


def get_order(raw_args: dict, conn=None) -> dict:
    args, error = parse_args(GetOrderArgs, raw_args)
    if error:
        return error

    with use_connection(conn) as db:
        order = db.execute(
            "SELECT id, customer_id, status, placed_at, delivered_at, total_cents "
            "FROM orders WHERE id = ?",
            (args.order_id,),
        ).fetchone()
        if order is None:
            return err(
                "ORDER_NOT_FOUND",
                f"No order with id {args.order_id}.",
                "Order IDs are numbers like 1001. Ask the customer to confirm the order number.",
            )

        items = db.execute(
            "SELECT sku, name, quantity, price_cents, category "
            "FROM order_items WHERE order_id = ? ORDER BY id",
            (args.order_id,),
        ).fetchall()
        refunded = db.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) FROM refunds WHERE order_id = ?",
            (args.order_id,),
        ).fetchone()[0]

        return ok(
            {
                "order_id": order["id"],
                "customer_id": order["customer_id"],
                "status": order["status"],
                "placed_at": order["placed_at"],
                "delivered_at": order["delivered_at"],
                "total_cents": order["total_cents"],
                "refunded_cents": refunded,
                "items": [dict(item) for item in items],
            }
        )


# ---------- list_customer_orders ----------

class ListCustomerOrdersArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: int = Field(..., gt=0, description="Numeric customer ID.")
    limit: int = Field(5, ge=1, le=20, description="How many recent orders to return (1-20).")


LIST_CUSTOMER_ORDERS_SPEC = {
    "name": "list_customer_orders",
    "description": (
        "List a customer's most recent orders, newest first, by numeric customer ID. "
        "Returns a short summary of each order (not the items). Use this when the "
        "customer does not know their order number. Money amounts are in cents. "
        "To see full details of one order, call get_order afterwards."
    ),
    "input_schema": ListCustomerOrdersArgs.model_json_schema(),
}


def list_customer_orders(raw_args: dict, conn=None) -> dict:
    args, error = parse_args(ListCustomerOrdersArgs, raw_args)
    if error:
        return error

    with use_connection(conn) as db:
        customer = db.execute(
            "SELECT id FROM customers WHERE id = ?", (args.customer_id,)
        ).fetchone()
        if customer is None:
            return err(
                "CUSTOMER_NOT_FOUND",
                f"No customer with id {args.customer_id}.",
                "Customer IDs are numbers. Confirm the customer's identity first.",
            )

        rows = db.execute(
            "SELECT id, status, placed_at, total_cents FROM orders "
            "WHERE customer_id = ? ORDER BY placed_at DESC, id DESC LIMIT ?",
            (args.customer_id, args.limit),
        ).fetchall()

        return ok(
            {
                "customer_id": args.customer_id,
                "orders": [
                    {
                        "order_id": r["id"],
                        "status": r["status"],
                        "placed_at": r["placed_at"],
                        "total_cents": r["total_cents"],
                    }
                    for r in rows
                ],
            }
        )