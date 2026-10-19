"""
Tests against the real LLM. Excluded by default (pytest.ini); run with

    pytest -m live

Needs OPENROUTER_API_KEY in the environment or .env. These assert only on
structure and safety properties, never on the wording of LLM text.
"""

import os

import pytest

import config
import governance as g
import llm_config
import workflow

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.getenv("OPENROUTER_API_KEY"), reason="OPENROUTER_API_KEY not set"),
]


@pytest.fixture(autouse=True)
def live_mode(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODE", "live")
    llm_config._llm_client = None


@pytest.mark.parametrize("product_id, expected_status", [(1, g.NO_ACTION_REQUIRED), (2, g.PENDING_APPROVAL)])
def test_live_cycle_produces_valid_structured_outputs(product_id, expected_status):
    record = workflow.run_cycle(product_id)
    assert record["llm_mode"] == "live"
    for name in ["demand", "risk", "logistics"]:
        meta = record["agent_outputs"][name]["meta"]
        assert meta["source"] == "llm"
        assert meta["output_valid"], f"{name}: {meta['issues']}"
    assert record["final_decision"]["meta"]["output_valid"], record["final_decision"]["meta"]["issues"]
    # Safety property, whatever the LLM said: the status follows policy.
    assert record["status"] == expected_status
