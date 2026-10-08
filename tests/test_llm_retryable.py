import anthropic
import pytest

try:
    import httpx2 as httpx          # newer SDK versions
except ImportError:
    import httpx

from shopdesk.llm import is_retryable

REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def status_error(cls, status):
    return cls("test", response=httpx.Response(status, request=REQUEST), body=None)


@pytest.mark.parametrize("make", [
    lambda: status_error(anthropic.RateLimitError, 429),
    lambda: status_error(anthropic.InternalServerError, 500),
    lambda: status_error(anthropic.InternalServerError, 529),     # "overloaded"
    lambda: anthropic.APIConnectionError(request=REQUEST),
    lambda: anthropic.APITimeoutError(request=REQUEST),
])
def test_temporary_errors_are_retried(make):
    assert is_retryable(make()) is True


@pytest.mark.parametrize("make", [
    lambda: status_error(anthropic.BadRequestError, 400),         # our request is wrong
    lambda: status_error(anthropic.AuthenticationError, 401),     # bad API key
    lambda: status_error(anthropic.PermissionDeniedError, 403),
    lambda: status_error(anthropic.NotFoundError, 404),           # e.g. a typo in the model name
    lambda: ValueError("a bug in our own code"),
])
def test_our_own_mistakes_are_not_retried(make):
    assert is_retryable(make()) is False
