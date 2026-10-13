from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from shopdesk.db import get_connection


def ok(data: Any) -> dict:
    """A successful tool result."""
    return {"ok": True, "data": data}


def err(code: str, message: str, hint: str | None = None) -> dict:
    """A failed tool result. Tools RETURN errors; they don't raise them."""
    error = {"code": code, "message": message}
    if hint:
        error["hint"] = hint
    return {"ok": False, "error": error}


def parse_args(model_cls, raw_args: dict):
    """
    Validate raw arguments (from the model) with a Pydantic model.
    Returns (parsed_args, None) on success or (None, error_result) on failure.
    """
    try:
        return model_cls(**raw_args), None
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in e['loc']) or 'arguments'}: {e['msg']}"
            for e in exc.errors()
        )
        return None, err(
            "INVALID_INPUT",
            problems,
            "Check the argument names and types against the tool's input schema.",
        )
    except TypeError:
        return None, err("INVALID_INPUT", "Arguments must be a JSON object.")


@contextmanager
def use_connection(conn=None):
    """
    Use the connection you're given (tests do this), or open and close one.
    """
    if conn is not None:
        yield conn
    else:
        own = get_connection()
        try:
            yield own
        finally:
            own.close()


@dataclass(frozen=True)
class Session:
    """
    WHO the customer is. It is created by OUR code from the sign-in, and passed to every tool call
    by the agent loop. The model never sees it as an argument, so it can neither supply nor change it.
    """
    customer_id: int


def visible_to(session, owner_id) -> bool:
    """May this session see data owned by owner_id? (session=None is an internal call: tests, scripts, staff.)"""
    return session is None or session.customer_id == owner_id


def order_not_found(order_id: int) -> dict:
    """
    ONE error for both 'no such order' and 'not yours', worded identically, so the agent
    (or anyone talking to it) cannot use the difference to discover which orders exist.
    """
    return err(
        "ORDER_NOT_FOUND",
        f"No order with id {order_id}.",
        "Order IDs are numbers like 1001. Ask the customer to confirm the order number.",
    )
