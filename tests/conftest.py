"""
Shared pytest fixtures.

* Forces LLM_MODE=offline before any project module is imported, so the
  default suite never needs an API key or network access.
* Every test gets its own freshly seeded SQLite file (fresh_db, autouse).
* mock_llm installs per-agent fake LLM answers.

Tests that call the real LLM live in tests/live and are marked `live`.
"""

import contextlib
import io
import os
import sys
from pathlib import Path

os.environ["LLM_MODE"] = "offline"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

import pytest  # noqa: E402

import config  # noqa: E402
import db_init  # noqa: E402
import db_service  # noqa: E402
import llm_config  # noqa: E402
from models import PurchaseOrder  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    previous = str(db_service.engine.url)
    db_service.configure(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    db_init.init_database()
    with contextlib.redirect_stdout(io.StringIO()):
        db_init.seed_data(db_service.engine)
    config.LLM_MODE = "offline"
    yield
    llm_config.set_llm_override(None)
    db_service.engine.dispose()
    db_service.configure(previous)


@pytest.fixture
def mock_llm():
    """
    mock_llm({"coordinator": "text", "demand": TimeoutError("x")})
    Listed agents get the given text (or raise the given exception);
    other agents keep their offline rule answer.
    """
    def install(answers: dict):
        def fake(agent, prompt, offline_response):
            if agent not in answers:
                return offline_response
            answer = answers[agent]
            if isinstance(answer, Exception):
                raise answer
            return answer
        llm_config.set_llm_override(fake)
    yield install
    llm_config.set_llm_override(None)


@pytest.fixture
def po_count():
    def count():
        with db_service.get_session() as s:
            return s.query(PurchaseOrder).count()
    return count


def make_snapshot(**changes) -> dict:
    """A valid snapshot shaped like the product-2 seed data, for unit tests."""
    snapshot = {
        "product": {"id": 2, "name": "Widget B - Premium", "sku": "WGT-B-002"},
        "inventory": {"quantity": 50, "reorder_point": 100},
        "inventory_record_count": 1,
        "suppliers": [
            {"id": 1, "name": "Reliable Corp", "lead_time_days": 5, "reliability_score": 0.95},
            {"id": 2, "name": "Fast Shipping Inc", "lead_time_days": 2, "reliability_score": 0.85},
        ],
        "purchase_orders": [],
        "shipments": [],
    }
    snapshot.update(changes)
    return snapshot
