# The refund rules as DATA. This table mirrors data/policies/refund.md.

# category -> (standard window in days, VIP window in days). None = never refundable.
REFUND_WINDOWS = {
    "clothing": (30, 30),
    "home": (30, 30),
    "electronics": (14, 21),
    "gift_card": None,
}

APPROVAL_LIMIT_CENTS = 20000   # refunds ABOVE this amount need a human ($200.00)


def window_days(category: str, tier: str):
    """Refund window in days for one category and customer tier, or None if not refundable."""
    windows = REFUND_WINDOWS[category]
    if windows is None:
        return None
    standard, vip = windows
    return vip if tier == "vip" else standard