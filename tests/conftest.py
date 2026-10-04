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