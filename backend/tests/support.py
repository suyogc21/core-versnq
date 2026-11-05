from sqlalchemy.engine import make_url


def assert_test_database(url: str) -> None:
    """Refuse to touch any database whose name does not end in `_test`."""
    name = make_url(url).database or ""
    if not name.endswith("_test"):
        raise RuntimeError(f"Tests must run on a database ending in '_test', got '{name}'")
