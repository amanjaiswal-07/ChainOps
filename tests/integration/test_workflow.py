"""End-to-end graph runs and the event pipeline (offline rules or mocked LLM)."""

from datetime import datetime, timedelta, timezone

import pytest

import governance as g
import workflow
from graph import AGENT_NODES


def agents_ran(record):
    return [t["node"] for t in record["agent_trace"] or [] if t["node"] in AGENT_NODES]


def event(**overrides):
    payload = {"event_id": "evt-1", "event_type": "INVENTORY_LEVEL_CHANGED", "product_id": 1,
               "observed_quantity": 40, "occurred_at": datetime.now(timezone.utc).isoformat()}
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("product_id, status, decision, quantity", [
    (1, g.NO_ACTION_REQUIRED, "HOLD", 0),
    (2, g.PENDING_APPROVAL, "REORDER", 150),
    (3, g.PENDING_APPROVAL, "REORDER", 140),
])
def test_seed_products(product_id, status, decision, quantity, po_count):
    before = po_count()
    record = workflow.run_cycle(product_id)
    assert record["status"] == status
    assert record["final_decision"]["decision_type"] == decision
    assert record["final_decision"]["details"]["quantity"] == quantity
    assert agents_ran(record) == AGENT_NODES  # all five, in order
    assert record["validation_status"] == "PASSED"
    assert record["llm_mode"] == "offline"
    assert po_count() == before  # nothing executes without approval


def test_record_explains_itself():
    record = workflow.run_cycle(2)
    assert record["snapshot"]["inventory"]["quantity"] == 50
    assert record["risk_reasons"] and record["agent_outputs"]["risk"]["reasoning"]
    assert [t["node"] for t in record["agent_trace"]][:2] == ["ingest_data", "validate_data"]
    assert record["latency_ms"] is not None and record["created_at"] and record["updated_at"]


def test_invalid_data_stops_before_agents():
    record = workflow.run_cycle(2, overlay={"inventory_quantity": -15})
    assert record["status"] == g.VALIDATION_FAILED
    assert agents_ran(record) == []
    assert record["final_decision"] is None


def test_malformed_llm_output_is_flagged_and_needs_approval(mock_llm):
    mock_llm({"coordinator": "we should order something"})
    record = workflow.run_cycle(2)
    meta = record["final_decision"]["meta"]
    assert meta["output_valid"] is False and meta["fallback_used"] is True
    assert record["final_decision"]["details"] == {"supplier_id": 1, "quantity": 150, "expedite": True}
    assert record["status"] == g.PENDING_APPROVAL


def test_llm_outage_recovers_with_rule_fallback(mock_llm):
    mock_llm({name: TimeoutError("timed out") for name in ["demand", "inventory", "risk", "logistics", "coordinator"]})
    record = workflow.run_cycle(3)
    assert record["status"] == g.PENDING_APPROVAL
    assert record["agent_outputs"]["risk"]["meta"]["issues"][0].startswith("LLM call failed: TimeoutError")
    assert record["llm_mode"] == "mock"


def test_llm_cannot_turn_a_needed_reorder_into_hold(mock_llm):
    mock_llm({"coordinator": "DECISION_TYPE: HOLD\nSUPPLIER_ID: N/A\nQUANTITY: 0\nEXPEDITE: false\nREASONING: fine"})
    record = workflow.run_cycle(2)
    assert record["final_decision"]["decision_type"] == "REORDER"
    assert record["final_decision"]["details"]["supplier_id"] == 1
    assert record["status"] == g.PENDING_APPROVAL
    assert any("coordinator agent LLM said decision_type=HOLD" in r for r in record["risk_reasons"])


def test_llm_unknown_supplier_is_replaced(mock_llm):
    mock_llm({"coordinator": "DECISION_TYPE: REORDER\nSUPPLIER_ID: 42\nQUANTITY: 150\nEXPEDITE: true\nREASONING: x"})
    record = workflow.run_cycle(2)
    assert record["final_decision"]["details"]["supplier_id"] == 1
    assert record["final_decision"]["meta"]["output_valid"] is False


def test_llm_may_choose_another_valid_supplier(mock_llm):
    mock_llm({"coordinator": "DECISION_TYPE: REORDER\nSUPPLIER_ID: 2\nQUANTITY: 150\nEXPEDITE: true\nREASONING: faster"})
    record = workflow.run_cycle(2)
    assert record["final_decision"]["details"]["supplier_id"] == 2
    assert record["final_decision"]["meta"]["supplier_choice"] == {"llm": 2, "most_reliable": 1}


def test_unexpected_error_is_recorded_as_failed(monkeypatch):
    import nodes.data_ingestion as ingestion

    def broken(product_id=None):
        raise RuntimeError("database exploded")
    monkeypatch.setattr(ingestion, "read_supply_chain_snapshot", broken)
    workflow._graph = None  # rebuild with the patched node module
    try:
        record = workflow.run_cycle(1)
    finally:
        workflow._graph = None
    assert record["status"] == g.FAILED
    assert record["error"] == {"stage": "workflow", "last_completed_node": None, "type": "RuntimeError",
                               "message": "database exploded"}


def test_approve_flow_end_to_end(po_count):
    before = po_count()
    record = workflow.run_cycle(2)
    done = g.approve(record["decision_id"], "alice")
    assert done["status"] == g.EXECUTED and po_count() == before + 1
    # The new PO is visible to the next cycle: demand risk now sees an active order.
    assert workflow.run_cycle(2)["snapshot"]["purchase_orders"]


def test_scenario_runs_are_dry_runs_via_backend_interface(po_count):
    from backend_interface import run_one_cycle
    before = po_count()
    record = run_one_cycle(1, overlay={"inventory_quantity": 60})
    assert record["trigger"] == "SCENARIO" and record["dry_run"] is True
    assert g.approve(record["decision_id"], "alice")["execution_result"]["mode"] == "dry_run"
    assert po_count() == before


# --- Event pipeline ---------------------------------------------------------------

def test_event_triggers_cycle():
    record = workflow.process_event(event())
    assert record["trigger"] == "EVENT" and record["event_type"] == "INVENTORY_LEVEL_CHANGED"
    assert record["status"] == g.PENDING_APPROVAL
    assert record["snapshot"]["inventory"]["quantity"] == 40
    assert "below reorder point" in record["trigger_reason"]


def test_duplicate_event_returns_same_decision():
    first = workflow.process_event(event())
    second = workflow.process_event(event())
    assert second["duplicate"] is True and second["decision_id"] == first["decision_id"]
    assert len(g.list_records()) == 1


def test_event_below_threshold_is_not_triggered():
    record = workflow.process_event(event(observed_quantity=500))
    assert record["status"] == g.NOT_TRIGGERED and record["agent_trace"] is None


def test_stale_event_fails_validation():
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    record = workflow.process_event(event(occurred_at=old))
    assert record["status"] == g.VALIDATION_FAILED
    assert record["validation_report"]["errors"][0]["code"] == "STALE_EVENT"


def test_event_for_unknown_product_fails_validation():
    record = workflow.process_event(event(product_id=999))
    assert record["status"] == g.VALIDATION_FAILED
    assert "does not exist" in record["validation_report"]["errors"][0]["message"]


def test_shipment_of_another_product_is_inconsistent():
    payload = event(event_type="SHIPMENT_DELAYED", shipment_id=2, delay_days=4)
    del payload["observed_quantity"]
    record = workflow.process_event(payload)
    assert record["status"] == g.VALIDATION_FAILED
    assert record["validation_report"]["errors"][0]["code"] == "INCONSISTENT_REFERENCE"
