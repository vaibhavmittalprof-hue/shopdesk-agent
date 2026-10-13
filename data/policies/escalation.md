# Escalation to a Human Agent

## When the assistant must hand over
The assistant creates a support ticket for a human agent when:
- a refund would bring the total refunded on an order above $200.00,
- the customer says an item is defective or damaged,
- the customer asks to speak to a human,
- the customer asks for an exception to a policy,
- an order's records look incomplete or wrong.

## What the assistant must not say
The assistant must never promise that a human agent will approve, complete or process a request, and must not say that an agent has already been assigned. It says that a human agent will review the request and follow up.

## Response time
Human agents normally follow up within 1 business day. This is a target, not a promise.

## Ticket reasons
Use REFUND_NEEDS_APPROVAL for refunds over the limit, DEFECTIVE_ITEM for defect claims, CUSTOMER_REQUEST
when the customer asks for a human, and OTHER for everything else, including requests for an exception
(the summary should then say that the customer is asking for an exception).