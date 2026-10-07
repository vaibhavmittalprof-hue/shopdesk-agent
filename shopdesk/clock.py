from datetime import datetime

# The shop's "today". It is FIXED so the fake data and the tests never change.
# (For a real shop you would return datetime.now() instead.)
SHOP_NOW = datetime(2026, 10, 1, 12, 0, 0)


def current_time() -> datetime:
    return SHOP_NOW