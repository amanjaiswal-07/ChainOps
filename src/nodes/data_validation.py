"""
Validation gate between data ingestion and the agents.

If the snapshot breaks a business rule, no agent runs: the graph goes
straight to `validation_failed` and the cycle ends with no recommendation.
This is what stops bad data from silently producing a purchase order.
"""

from state import SupplyChainState
from validation import FAILED, validate_snapshot


def data_validation_node(state: SupplyChainState) -> dict:
    """Deterministic, no LLM. Stores the full report in state['validation']."""
    return {'validation': validate_snapshot(state['db_snapshot'])}


def route_after_validation(state: SupplyChainState) -> str:
    """Conditional edge: 'invalid' stops the cycle, 'valid' continues to the agents."""
    return "invalid" if state['validation']['status'] == FAILED else "valid"


def validation_failed_node(state: SupplyChainState) -> dict:
    """Terminal node for rejected input. Nothing is recommended or executed."""
    return {
        'final_decision': None,
        'decision_risk': None,
        'risk_reasons': [f"{e['code']}: {e['message']}" for e in state['validation']['errors']],
        'approval_status': "VALIDATION_FAILED",
        'human_feedback': None,
    }
