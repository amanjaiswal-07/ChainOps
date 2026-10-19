"""Layer 3: AI-output validation (strict parsing and reconciliation with rules)."""

import pytest

from agents.outputs import (OutputParseError, parse_coordinator, parse_demand, parse_logistics, parse_risk,
                            resolve)
from llm_config import LLMResponse


def test_well_formed_outputs_parse():
    assert parse_demand("DEMAND_RISK: HIGH\nREASONING: stock is low").demand_risk == "HIGH"
    risk = parse_risk("SUPPLIER_RISK: LOW\nLOGISTICS_RISK: HIGH\nREASONING: late ship")
    assert (risk.supplier_risk, risk.logistics_risk) == ("LOW", "HIGH")
    assert parse_logistics("EXPEDITE: true\nREASONING: urgent").expedite is True
    coord = parse_coordinator("DECISION_TYPE: REORDER\nSUPPLIER_ID: 1\nQUANTITY: 150\nEXPEDITE: false\nREASONING: ok")
    assert (coord.decision_type, coord.supplier_id, coord.quantity, coord.expedite) == ("REORDER", 1, 150, False)


def test_markdown_formatting_is_tolerated():
    text = "**DEMAND_RISK:** **HIGH**\n\n**REASONING:** stock is below the reorder point"
    assert parse_demand(text).demand_risk == "HIGH"


def test_restated_fields_inside_reasoning_do_not_clash():
    text = ("DECISION_TYPE: HOLD\nSUPPLIER_ID: N/A\nQUANTITY: 0\nEXPEDITE: false\n"
            "REASONING: We considered\n- EXPEDITE: true\nbut rejected it.")
    assert parse_coordinator(text).expedite is False


@pytest.mark.parametrize("text, message", [
    ("I think risk is fine.", "missing field DEMAND_RISK"),
    ("DEMAND_RISK: MEDIUM\nREASONING: x", "invalid value"),
    ("DEMAND_RISK: HIGH\nDEMAND_RISK: LOW\nREASONING: x", "conflicting values"),
    ("DEMAND_RISK: HIGH", "missing REASONING"),
    ("DEMAND_RISK: HIGH\nREASONING:   ", "missing REASONING"),
])
def test_malformed_demand_outputs_raise(text, message):
    with pytest.raises(OutputParseError, match=message):
        parse_demand(text)


@pytest.mark.parametrize("text", [
    "DECISION_TYPE: REORDER\nSUPPLIER_ID: N/A\nQUANTITY: 150\nEXPEDITE: false\nREASONING: x",  # no supplier
    "DECISION_TYPE: REORDER\nSUPPLIER_ID: 1\nQUANTITY: 0\nEXPEDITE: false\nREASONING: x",      # zero qty
    "DECISION_TYPE: HOLD\nSUPPLIER_ID: N/A\nQUANTITY: 50\nEXPEDITE: false\nREASONING: x",      # HOLD with qty
    "DECISION_TYPE: REORDER\nSUPPLIER_ID: 1\nQUANTITY: -5\nEXPEDITE: false\nREASONING: x",     # negative
    "DECISION_TYPE: REORDER\nSUPPLIER_ID: 1\nQUANTITY: 150\nEXPEDITE: maybe\nREASONING: x",    # bad bool
])
def test_inconsistent_coordinator_outputs_raise(text):
    with pytest.raises(OutputParseError):
        parse_coordinator(text)


BASELINE = {"demand_risk": "HIGH", "reasoning": "rule says high"}


def test_resolve_accepts_agreeing_llm_answer():
    out = resolve(LLMResponse("DEMAND_RISK: HIGH\nREASONING: llm", "llm"), parse_demand, BASELINE,
                  risk_fields=("demand_risk",))
    assert out["reasoning"] == "llm"
    assert out["meta"]["output_valid"] and not out["meta"]["disagreements"]


def test_llm_cannot_downgrade_risk():
    out = resolve(LLMResponse("DEMAND_RISK: LOW\nREASONING: fine", "llm"), parse_demand, BASELINE,
                  risk_fields=("demand_risk",))
    assert out["demand_risk"] == "HIGH"
    assert out["meta"]["disagreements"] == {"demand_risk": {"llm": "LOW", "rule": "HIGH"}}


def test_llm_can_escalate_risk():
    low = {"demand_risk": "LOW", "reasoning": "rule says low"}
    out = resolve(LLMResponse("DEMAND_RISK: HIGH\nREASONING: worried", "llm"), parse_demand, low,
                  risk_fields=("demand_risk",))
    assert out["demand_risk"] == "HIGH"
    assert "demand_risk" in out["meta"]["disagreements"]


def test_rule_fields_override_llm():
    baseline = {"expedite": True, "reasoning": "rule"}
    out = resolve(LLMResponse("EXPEDITE: false\nREASONING: save money", "llm"), parse_logistics, baseline,
                  rule_fields=("expedite",))
    assert out["expedite"] is True and "expedite" in out["meta"]["disagreements"]


def test_malformed_output_falls_back_to_rule_and_is_flagged():
    out = resolve(LLMResponse("no idea", "llm"), parse_demand, BASELINE, risk_fields=("demand_risk",))
    assert out["demand_risk"] == "HIGH"
    assert out["meta"]["output_valid"] is False and out["meta"]["fallback_used"] is True
    assert "malformed LLM output" in out["meta"]["issues"][0]


def test_llm_error_falls_back_to_rule_and_is_flagged():
    out = resolve(LLMResponse(None, "llm", error="TimeoutError: slow"), parse_demand, BASELINE)
    assert out["meta"]["output_valid"] is False
    assert "TimeoutError" in out["meta"]["issues"][0]
