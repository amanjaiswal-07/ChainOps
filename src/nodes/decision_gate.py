import config
from state import SupplyChainState

AGENTS = ("demand", "inventory", "risk", "logistics")


def assess_decision_risk(state: SupplyChainState) -> tuple[str, list[str]]:
    """
    Explicit approval policy. Returns (risk_level, reasons).

    A REORDER is HIGH risk (needs a human) if ANY of these holds:
      1. demand, supplier or logistics risk is HIGH
      2. any of those risk signals is missing/UNKNOWN
      3. an agent's LLM output failed validation and a rule fallback was used
      4. an LLM answer disagreed with the deterministic rule baseline
      5. the order quantity exceeds APPROVAL_QUANTITY_THRESHOLD
      6. the order quantity was capped at MAX_ORDER_QUANTITY
      7. the input data passed validation only with data-quality warnings

    HOLD places no order and has no side effects, so it never needs
    approval (original project rule). Any AI issues are still listed
    in the reasons for the audit trail.
    """
    agent_outputs = state['agent_outputs']
    risk_output = agent_outputs.get('risk', {})
    demand_output = agent_outputs.get('demand', {})
    final_decision = state.get('final_decision') or {}
    decision_type = final_decision.get('decision_type', 'HOLD')
    quantity = (final_decision.get('details') or {}).get('quantity', 0) or 0

    reasons: list[str] = []

    # 1-2. Operational risk signals from the agents
    signals = {
        "demand risk": demand_output.get('demand_risk', 'UNKNOWN'),
        "supplier risk": risk_output.get('supplier_risk', 'UNKNOWN'),
        "logistics risk": risk_output.get('logistics_risk', 'UNKNOWN'),
    }
    for name, level in signals.items():
        if level == 'HIGH':
            reasons.append(f"{name} is HIGH")
        elif level != 'LOW':
            reasons.append(f"{name} is {level}: unknown risk defaults to human review")

    # 3-4. Trust in the AI outputs
    metas = {name: agent_outputs.get(name, {}).get('meta', {}) for name in AGENTS}
    metas["coordinator"] = final_decision.get('meta', {})
    for name, meta in metas.items():
        if meta.get('output_valid') is False:
            reasons.append(f"{name} agent output failed validation ({'; '.join(meta.get('issues', [])) or 'see record'})")
        for field, values in (meta.get('disagreements') or {}).items():
            reasons.append(f"{name} agent LLM said {field}={values['llm']} but the rule gives {values['rule']}")

    # 5-6. Size of the action
    if quantity > config.APPROVAL_QUANTITY_THRESHOLD:
        reasons.append(f"order quantity {quantity} exceeds the approval threshold {config.APPROVAL_QUANTITY_THRESHOLD}")
    if agent_outputs.get('inventory', {}).get('capped'):
        reasons.append(f"order quantity was capped at the {config.MAX_ORDER_QUANTITY}-unit ceiling")

    # 7. Data quality
    for warning in (state.get('validation') or {}).get('warnings', []):
        reasons.append(f"data-quality warning: {warning['message']}")

    if decision_type == 'HOLD':
        notes = [f"note: {r}" for r in reasons]
        return 'LOW', ["HOLD places no order, so it completes without approval"] + notes

    if reasons:
        return 'HIGH', reasons
    return 'LOW', ["all risk signals LOW, AI outputs valid and consistent, quantity within policy"]


def decision_gate_node(state: SupplyChainState) -> dict:
    """
    Deterministic decision gate - NO LLM.

    Routes workflow based on the policy in assess_decision_risk():
    - HIGH risk -> requires human approval
    - LOW risk -> auto-approve (or no action for HOLD)

    Returns:
        Partial state update with decision_risk and the reasons for it
    """
    decision_risk, reasons = assess_decision_risk(state)
    return {
        'decision_risk': decision_risk,
        'risk_reasons': reasons,
    }


def should_request_human_approval(state: SupplyChainState) -> str:
    """
    Conditional edge function for LangGraph routing.

    Used by graph.add_conditional_edges() to determine next node.

    Returns:
        "human_approval" if HIGH risk (or anything other than LOW)
        "auto_execute" if LOW risk
    """
    return "auto_execute" if state.get('decision_risk') == 'LOW' else "human_approval"
