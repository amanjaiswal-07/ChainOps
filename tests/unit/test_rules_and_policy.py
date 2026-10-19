"""Deterministic agent rules and the decision-gate approval policy."""

from datetime import timedelta

import config
from agents.rules import coordinator_rule, demand_rule, inventory_rule, logistics_rule, risk_rule
from conftest import make_snapshot
from models import utcnow
from nodes.decision_gate import assess_decision_risk, should_request_human_approval


def test_demand_rule():
    assert demand_rule(make_snapshot())["demand_risk"] == "HIGH"  # below ROP, no PO
    po = {"id": 1, "supplier_id": 1, "quantity": 10, "status": "pending", "created_at": None}
    ok = make_snapshot(inventory={"quantity": 150, "reorder_point": 100}, purchase_orders=[po])
    assert demand_rule(ok)["demand_risk"] == "LOW"


def test_inventory_rule_and_cap():
    assert inventory_rule(make_snapshot())["quantity"] == 150  # 2*100 - 50
    assert inventory_rule(make_snapshot(inventory={"quantity": 100, "reorder_point": 100}))["action"] == "HOLD"
    huge = inventory_rule(make_snapshot(inventory={"quantity": 0, "reorder_point": 800}))
    assert huge["capped"] and huge["quantity"] == config.MAX_ORDER_QUANTITY and huge["uncapped_quantity"] == 1600


def test_risk_rule():
    soon = {"id": 1, "po_id": 1, "status": "in_transit", "expected_arrival": (utcnow() + timedelta(days=3)).isoformat()}
    late = {**soon, "expected_arrival": (utcnow() + timedelta(days=12)).isoformat()}
    overdue = {**soon, "expected_arrival": (utcnow() - timedelta(days=2)).isoformat()}
    reliable = [{"id": 1, "name": "A", "lead_time_days": 5, "reliability_score": 0.95}]
    calm = risk_rule(make_snapshot(suppliers=reliable, shipments=[soon]))
    assert (calm["supplier_risk"], calm["logistics_risk"]) == ("LOW", "LOW")
    assert risk_rule(make_snapshot(shipments=[soon]))["supplier_risk"] == "HIGH"  # one supplier at 85%
    assert risk_rule(make_snapshot(suppliers=reliable, shipments=[late]))["logistics_risk"] == "HIGH"
    assert "overdue" in risk_rule(make_snapshot(suppliers=reliable, shipments=[overdue]))["reasoning"]
    assert risk_rule(make_snapshot(suppliers=reliable))["logistics_risk"] == "HIGH"  # no shipments


def test_logistics_rule():
    snap = make_snapshot(inventory={"quantity": 150, "reorder_point": 100})
    calm = {"demand_risk": "LOW"}, {"supplier_risk": "LOW", "logistics_risk": "LOW"}
    assert logistics_rule(snap, {"action": "HOLD"}, *calm)["expedite"] is False
    assert logistics_rule(make_snapshot(), {"action": "REORDER"}, *calm)["expedite"] is True
    assert logistics_rule(snap, {"action": "HOLD"}, {"demand_risk": "HIGH"},
                          {"supplier_risk": "LOW", "logistics_risk": "HIGH"})["expedite"] is True


def test_coordinator_rule_picks_most_reliable_supplier():
    out = coordinator_rule(make_snapshot(), {"inventory": {"action": "REORDER", "quantity": 150},
                                             "logistics": {"expedite": True}})
    assert (out["decision_type"], out["supplier_id"], out["quantity"], out["expedite"]) == ("REORDER", 1, 150, True)


# --- Approval policy ----------------------------------------------------------

def _state(decision_type="REORDER", quantity=150, risks=("LOW", "LOW", "LOW"), metas=None, warnings=()):
    meta = {"output_valid": True, "disagreements": {}}
    outputs = {
        "demand": {"demand_risk": risks[0], "meta": dict(meta)},
        "risk": {"supplier_risk": risks[1], "logistics_risk": risks[2], "meta": dict(meta)},
        "inventory": {"action": decision_type, "quantity": quantity, "capped": False, "meta": dict(meta)},
        "logistics": {"expedite": False, "meta": dict(meta)},
    }
    for name, m in (metas or {}).items():
        outputs[name]["meta"] = m
    return {"agent_outputs": outputs,
            "final_decision": {"decision_type": decision_type, "details": {"quantity": quantity}, "meta": dict(meta)},
            "validation": {"warnings": [{"message": w} for w in warnings]}}


def test_all_low_reorder_is_auto_approved():
    risk, reasons = assess_decision_risk(_state())
    assert risk == "LOW"
    assert should_request_human_approval({"decision_risk": risk}) == "auto_execute"


def test_any_high_signal_requires_approval():
    risk, reasons = assess_decision_risk(_state(risks=("LOW", "HIGH", "LOW")))
    assert risk == "HIGH" and "supplier risk is HIGH" in reasons


def test_unknown_signal_requires_approval():
    risk, reasons = assess_decision_risk(_state(risks=("UNKNOWN", "LOW", "LOW")))
    assert risk == "HIGH" and any("UNKNOWN" in r for r in reasons)


def test_invalid_ai_output_requires_approval():
    bad = {"output_valid": False, "issues": ["malformed LLM output: x"], "disagreements": {}}
    risk, reasons = assess_decision_risk(_state(metas={"logistics": bad}))
    assert risk == "HIGH" and any("logistics agent output failed validation" in r for r in reasons)


def test_llm_rule_disagreement_requires_approval():
    disagree = {"output_valid": True, "disagreements": {"expedite": {"llm": False, "rule": True}}}
    risk, _ = assess_decision_risk(_state(metas={"logistics": disagree}))
    assert risk == "HIGH"


def test_non_default_supplier_choice_requires_approval():
    state = _state()
    state["final_decision"]["meta"]["supplier_choice"] = {"llm": 2, "most_reliable": 1}
    risk, reasons = assess_decision_risk(state)
    assert risk == "HIGH"
    assert "coordinator chose supplier 2 instead of the most reliable supplier 1" in reasons


def test_large_order_requires_approval():
    risk, reasons = assess_decision_risk(_state(quantity=config.APPROVAL_QUANTITY_THRESHOLD + 1))
    assert risk == "HIGH" and any("approval threshold" in r for r in reasons)


def test_data_quality_warning_requires_approval():
    risk, reasons = assess_decision_risk(_state(warnings=["PO open for 60 days"]))
    assert risk == "HIGH" and any("data-quality warning" in r for r in reasons)


def test_hold_never_needs_approval_but_keeps_notes():
    risk, reasons = assess_decision_risk(_state(decision_type="HOLD", quantity=0, risks=("HIGH", "HIGH", "HIGH")))
    assert risk == "LOW"
    assert any(r.startswith("note: ") for r in reasons)
