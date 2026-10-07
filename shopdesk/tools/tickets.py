from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shopdesk.clock import current_time
from shopdesk.tools.common import ok, parse_args, use_connection


class EscalateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: Literal["REFUND_NEEDS_APPROVAL", "DEFECTIVE_ITEM", "CUSTOMER_REQUEST", "OTHER"] = Field(
        ..., description="Why a human is needed.",
    )
    summary: str = Field(
        ..., min_length=10, max_length=500,
        description="What the customer wants and what has been checked so far, including "
                    "any order number and amount, so the human does not have to ask again.",
    )


ESCALATE_TO_HUMAN_SPEC = {
    "name": "escalate_to_human",
    "description": (
        "Hand the conversation to a human agent by creating a support ticket. Use it when "
        "a refund needs approval (REFUND_NEEDS_APPROVAL), when the customer says an item "
        "arrived defective or damaged (DEFECTIVE_ITEM), when the customer asks for a human "
        "(CUSTOMER_REQUEST), or when you cannot solve the problem (OTHER). Write the summary "
        "so the human can act without asking the customer again."
    ),
    "input_schema": EscalateArgs.model_json_schema(),
}


def escalate_to_human(raw_args: dict, conn=None) -> dict:
    args, error = parse_args(EscalateArgs, raw_args)
    if error:
        return error

    with use_connection(conn) as db:
        cursor = db.execute(
            # customer_id stays empty for now: the customer's identity must come from the
            # system, not from the model. We wire that up in M7.
            "INSERT INTO tickets (customer_id, summary, status, created_at) VALUES (NULL, ?, 'open', ?)",
            (f"[{args.reason}] {args.summary}", current_time().isoformat(timespec="seconds")),
        )
        db.commit()
        return ok(
            {
                "ticket_id": cursor.lastrowid,
                "status": "open",
                "message": "A human agent will follow up with the customer.",
            }
        )