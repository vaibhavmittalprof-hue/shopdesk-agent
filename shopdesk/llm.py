import os

import anthropic
from dotenv import load_dotenv

from shopdesk.retry import call_with_retries

# Read the .env file and copy its lines into environment variables
load_dotenv()

# max_retries=0: the SDK has hidden retries of its own. We turn them off so that OUR retry
# logic (which logs every retry) is the only one. timeout: give up on a call after 60 seconds.
client = anthropic.Anthropic(max_retries=0, timeout=60.0)

# Which model to use. Falls back to Haiku if LLM_MODEL isn't set.
MODEL = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")


def is_retryable(exc) -> bool:
    """True for TEMPORARY problems (try again). False for mistakes in our request (fix the code)."""
    if isinstance(exc, (anthropic.APIConnectionError,      # network problems, including timeouts
                        anthropic.RateLimitError,          # 429: too many requests
                        anthropic.InternalServerError)):   # 5xx: the server is having a bad moment
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code in (408, 409, 429) or exc.status_code >= 500
    return False


def chat(messages, tools=None, system=None, max_tokens=1024, on_retry=None):
    """Send a conversation to the model and return the raw response, retrying temporary errors."""
    kwargs = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools

    return call_with_retries(
        lambda: client.messages.create(**kwargs),
        is_retryable=is_retryable,
        on_retry=on_retry,
    )