# USD per 1 million tokens: (input price, output price).
# Prices change: check https://platform.claude.com/docs/en/about-claude/pricing
# Prompt-caching tokens are not counted here yet (we don't use caching).
PRICES_PER_MILLION = {
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


def estimate_cost(model, input_tokens, output_tokens):
    """Estimated dollars for one model call, or None if we don't know this model's price."""
    prices = PRICES_PER_MILLION.get(model)
    if prices is None:
        return None
    return (input_tokens * prices[0] + output_tokens * prices[1]) / 1_000_000