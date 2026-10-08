import pytest

from shopdesk.retry import backoff_delay, call_with_retries, retry_after_seconds


class Temporary(Exception):
    pass


class Permanent(Exception):
    pass


def is_temporary(exc):
    return isinstance(exc, Temporary)


def failing_then_ok(failures, error=Temporary):
    """A function that raises `failures` times and then returns 'ok'."""
    state = {"calls": 0}

    def fn():
        state["calls"] += 1
        if state["calls"] <= failures:
            raise error("boom")
        return "ok"

    fn.state = state
    return fn


# ---------- the waiting times ----------

def test_backoff_doubles_each_attempt_until_the_cap():
    top = lambda: 1.0                                # rand() = 1 -> the full ceiling
    assert [backoff_delay(n, base=1, cap=20, rand=top) for n in (1, 2, 3, 4, 5, 6)] == [1, 2, 4, 8, 16, 20]


def test_jitter_stays_between_half_and_the_full_ceiling():
    low, high = lambda: 0.0, lambda: 1.0
    assert backoff_delay(3, base=1, cap=20, rand=low) == 2.0     # ceiling is 4: half of it
    assert backoff_delay(3, base=1, cap=20, rand=high) == 4.0


# ---------- retrying ----------

def test_succeeds_after_temporary_failures():
    fn, sleeps = failing_then_ok(2), []
    assert call_with_retries(fn, is_retryable=is_temporary, sleep=sleeps.append) == "ok"
    assert fn.state["calls"] == 3
    assert len(sleeps) == 2                          # waited before each retry


def test_waits_get_longer():
    sleeps = []
    call_with_retries(failing_then_ok(3), is_retryable=is_temporary, sleep=sleeps.append, rand=lambda: 1.0)
    assert sleeps == [1.0, 2.0, 4.0]


def test_gives_up_after_max_attempts_and_raises_the_last_error():
    fn = failing_then_ok(99)
    with pytest.raises(Temporary):
        call_with_retries(fn, is_retryable=is_temporary, max_attempts=3, sleep=lambda s: None)
    assert fn.state["calls"] == 3


def test_permanent_errors_are_not_retried():
    fn = failing_then_ok(99, error=Permanent)
    with pytest.raises(Permanent):
        call_with_retries(fn, is_retryable=is_temporary, sleep=lambda s: None)
    assert fn.state["calls"] == 1                    # tried once, no retry


def test_no_error_means_no_waiting():
    sleeps = []
    assert call_with_retries(lambda: "fine", is_retryable=is_temporary, sleep=sleeps.append) == "fine"
    assert sleeps == []


def test_on_retry_is_told_about_every_retry():
    seen = []
    call_with_retries(failing_then_ok(2), is_retryable=is_temporary, sleep=lambda s: None,
                      on_retry=seen.append, rand=lambda: 1.0)
    assert [info["attempt"] for info in seen] == [1, 2]
    assert seen[0]["error"] == "Temporary" and seen[0]["wait_s"] == 1.0


# ---------- the server's own instructions ----------

class FakeResponse:
    def __init__(self, headers):
        self.headers = headers


class RateLimited(Temporary):
    def __init__(self, retry_after):
        super().__init__("slow down")
        self.response = FakeResponse({"retry-after": retry_after})


def test_retry_after_header_is_read():
    assert retry_after_seconds(RateLimited("7")) == 7.0
    assert retry_after_seconds(Temporary("no response attached")) is None
    assert retry_after_seconds(RateLimited("soon")) is None          # not a number


def test_server_wait_beats_our_shorter_wait_but_is_capped():
    state, sleeps = {"n": 0}, []

    def fn():
        state["n"] += 1
        if state["n"] <= 2:
            raise RateLimited("9" if state["n"] == 1 else "500")
        return "ok"

    call_with_retries(fn, is_retryable=is_temporary, sleep=sleeps.append, rand=lambda: 0.0, cap=20)
    assert sleeps == [9.0, 20.0]                     # 9s as asked; 500s capped at 20
