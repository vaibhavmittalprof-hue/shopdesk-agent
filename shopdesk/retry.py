import random
import time


def backoff_delay(attempt, base=1.0, cap=20.0, rand=random.random):
    """
    Seconds to wait before retry number `attempt` (1, 2, 3, ...).
    Exponential: 1s, 2s, 4s, 8s ... up to `cap`. Then 'jitter': pick a random point between
    half and all of that, so many clients don't all retry at the same instant.
    """
    ceiling = min(cap, base * (2 ** (attempt - 1)))
    return ceiling / 2 + rand() * ceiling / 2


def retry_after_seconds(exc):
    """If the server told us how long to wait (a Retry-After header), return it; else None."""
    try:
        value = exc.response.headers.get("retry-after")
        return float(value) if value is not None else None
    except Exception:
        return None


def call_with_retries(fn, *, is_retryable, max_attempts=4, base=1.0, cap=20.0,
                      on_retry=None, sleep=time.sleep, rand=random.random):
    """
    Call fn(). If it fails with an error that is_retryable() says is temporary,
    wait (with backoff + jitter) and try again, up to max_attempts calls in total.
    Errors that are not retryable, or the last failed attempt, are raised as they are.
    """
    attempt = 1
    while True:
        try:
            return fn()
        except Exception as exc:
            if not is_retryable(exc) or attempt >= max_attempts:
                raise
            wait = backoff_delay(attempt, base, cap, rand)
            server_wait = retry_after_seconds(exc)
            if server_wait is not None:
                wait = max(wait, min(server_wait, cap))     # respect the server, but not forever
            if on_retry:
                on_retry({"attempt": attempt, "error": type(exc).__name__, "wait_s": round(wait, 2)})
            sleep(wait)
            attempt += 1