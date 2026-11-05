import json
from pathlib import Path

from app.main import app

COMMITTED = Path(__file__).resolve().parents[3] / "docs/api/openapi.json"


def test_committed_api_spec_is_up_to_date():
    assert COMMITTED.exists(), "run `make openapi`"
    assert json.loads(COMMITTED.read_text()) == app.openapi(), "API changed: run `make openapi`"


def test_operation_ids_are_unique():
    ids = [op["operationId"] for path in app.openapi()["paths"].values() for op in path.values()]
    assert len(ids) == len(set(ids))
