from state import SupplyChainState


def decision_gate_node(state: SupplyChainState) -> dict:
    """
    Deterministic decision gate - NO LLM.
    
    Routes workflow based on risk assessment:
    - HIGH risk → requires human approval
    - LOW risk → auto-execute
    
    This is a pure routing decision based on simple rules.
    
    Args:
        state: Current graph state with agent outputs
        
    Returns:
        Partial state update with decision_risk classification
    """
    agent_outputs = state['agent_outputs']
    risk_output = agent_outputs.get('risk', {})
    demand_output = agent_outputs.get('demand', {})
    final_decision = state.get('final_decision', {})
    
    # Extract risk signals
    supplier_risk = risk_output.get('supplier_risk', 'UNKNOWN')
    logistics_risk = risk_output.get('logistics_risk', 'UNKNOWN')
    demand_risk = demand_output.get('demand_risk', 'UNKNOWN')
    decision_type = final_decision.get('decision_type', 'HOLD')
    
    # Deterministic gate logic
    # HIGH risk if ANY risk dimension is HIGH
    if supplier_risk == 'HIGH' or logistics_risk == 'HIGH' or demand_risk == 'HIGH':
        decision_risk = 'HIGH'
    elif supplier_risk == 'LOW' and logistics_risk == 'LOW' and demand_risk == 'LOW':
        decision_risk = 'LOW'
    else:
        # UNKNOWN risks default to requiring human review
        decision_risk = 'HIGH'
    
    # HOLD decisions can auto-execute (low consequence)
    if decision_type == 'HOLD':
        decision_risk = 'LOW'
    
    # Return risk classification
    # Downstream graph routing will use this to decide next node
    return {
        'decision_risk': decision_risk
    }


def should_request_human_approval(state: SupplyChainState) -> str:
    """
    Conditional edge function for LangGraph routing.
    
    Used by graph.add_conditional_edges() to determine next node.
    
    Returns:
        "human_approval" if HIGH risk
        "auto_execute" if LOW risk
    """
    decision_risk = state.get('decision_risk')
    
    if decision_risk == 'HIGH':
        return "human_approval"
    else:
        return "auto_execute"
