import pytest

from data.seed import main as seed_db
from shopdesk.db import get_connection


@pytest.fixture
def conn(tmp_path):
    """A fresh, fully seeded database for every test, in a temporary folder."""
    db_path = tmp_path / "test.db"
    seed_db(db_path, verbose=False)
    connection = get_connection(db_path)
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def keyword_search_for_tests(monkeypatch):
    """
    Tests must not depend on the developer's .env or on downloaded models, so every test starts with the
    plain keyword search, whatever POLICY_SEARCH says on this machine. (Tests of other searches pass their
    own index or setting explicitly.)
    """
    from shopdesk.tools import policy
    monkeypatch.setenv("POLICY_SEARCH", "bm25")
    policy._default_index.cache_clear()
    yield
    policy._default_index.cache_clear()