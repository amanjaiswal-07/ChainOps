from state import SupplyChainState
from llm_config import invoke_llm
from agents.outputs import parse_coordinator, resolve
from agents.rules import coordinator_rule


async def coordinator_agent_node(state: SupplyChainState) -> dict:
    """
    Synthesize all agent outputs into a final procurement decision.
    
    This is the CRITICAL coordination point where:
    - All agent recommendations are combined
    - Conflicts are explicitly resolved
    - Final decision is made with full explanation
    
    LLM handles conflict resolution and step-by-step reasoning.

    Guard rails on the LLM answer (see outputs.resolve):
    - decision type, quantity and expedite must follow the inventory and
      logistics agents, as the coordination rules below require; a
      mismatch is overridden and recorded
    - the supplier is the LLM's choice, but only if it exists
    - malformed output falls back to the rule baseline
    """
    snapshot = state['db_snapshot']
    agent_outputs = state['agent_outputs']
    
    # Extract all agent recommendations
    demand_output = agent_outputs.get('demand', {})
    inventory_output = agent_outputs.get('inventory', {})
    risk_output = agent_outputs.get('risk', {})
    logistics_output = agent_outputs.get('logistics', {})
    
    # Get current state
    current_qty = snapshot['inventory']['quantity']
    reorder_point = snapshot['inventory']['reorder_point']
    suppliers = snapshot['suppliers']
    
    # Format supplier options
    supplier_options = "\n".join([
        f"  - Supplier {s['id']} ({s['name']}): "
        f"reliability {s['reliability_score']:.0%}, "
        f"lead time {s['lead_time_days']} days"
        for s in suppliers
    ])
    
    # Build comprehensive coordination prompt
    prompt = f"""You are the coordination agent for a supply chain control tower.

Your job is to synthesize recommendations from multiple specialized agents
into ONE final procurement decision.

CURRENT STATE:
- Current inventory: {current_qty} units
- Reorder point: {reorder_point} units

AGENT RECOMMENDATIONS:

1. DEMAND AGENT:
   - Demand risk: {demand_output.get('demand_risk', 'N/A')}
   - Reasoning: {demand_output.get('reasoning', 'N/A')}

2. INVENTORY AGENT:
   - Action: {inventory_output.get('action', 'N/A')}
   - Quantity: {inventory_output.get('quantity', 0)} units
   - Reasoning: {inventory_output.get('reasoning', 'N/A')}

3. RISK AGENT:
   - Supplier risk: {risk_output.get('supplier_risk', 'N/A')}
   - Logistics risk: {risk_output.get('logistics_risk', 'N/A')}
   - Reasoning: {risk_output.get('reasoning', 'N/A')}

4. LOGISTICS AGENT:
   - Expedite shipping: {logistics_output.get('expedite', False)}
   - Reasoning: {logistics_output.get('reasoning', 'N/A')}

AVAILABLE SUPPLIERS:
{supplier_options}

COORDINATION RULES:

Decision Type:
- REORDER: if inventory agent recommends REORDER
- HOLD: if inventory agent recommends HOLD

If REORDER:
- Use quantity from inventory agent
- Select supplier with HIGHEST reliability score (unless supplier risk is HIGH, then explain trade-off)
- Apply expedited shipping if logistics agent recommends it

Conflict Resolution:
- If supplier risk is HIGH but reorder is needed: choose best available supplier and explain the risk acceptance
- If logistics risk is HIGH: factor this into supplier selection (prefer shorter lead times)
- If demand risk conflicts with inventory action: trust inventory agent (it has deterministic logic)

TASK:
1. Determine final decision type (REORDER or HOLD)
2. If REORDER: select supplier ID, confirm quantity, confirm expedite flag
3. Resolve any conflicts explicitly (explain which agent input takes priority and why)
4. Provide step-by-step reasoning for the final decision

FORMAT YOUR RESPONSE EXACTLY AS:

DECISION_TYPE: [REORDER or HOLD]
SUPPLIER_ID: [number or N/A if HOLD]
QUANTITY: [number or 0 if HOLD]
EXPEDITE: [true or false]
REASONING: [Step-by-step explanation covering:
  - Why this decision type was chosen
  - How supplier was selected (if REORDER)
  - How conflicts were resolved
  - What risks are being accepted or mitigated
]
"""
    
    baseline = coordinator_rule(snapshot, agent_outputs)
    response = invoke_llm(
        "coordinator",
        prompt,
        offline_response=(f"DECISION_TYPE: {baseline['decision_type']}\n"
                          f"SUPPLIER_ID: {baseline['supplier_id'] or 'N/A'}\n"
                          f"QUANTITY: {baseline['quantity']}\n"
                          f"EXPEDITE: {str(baseline['expedite']).lower()}\n"
                          f"REASONING: {baseline['reasoning']}"),
        run_config={
            "run_name": "coordinator_agent_final_decision",
            "tags": ["coordinator", "decision_synthesis", "conflict_resolution"],
            "metadata": {
                "agent": "coordinator",
                "num_agent_inputs": len(agent_outputs),
                "demand_risk": demand_output.get('demand_risk'),
                "inventory_action": inventory_output.get('action'),
                "supplier_risk": risk_output.get('supplier_risk'),
                "logistics_risk": risk_output.get('logistics_risk'),
                "expedite_recommended": logistics_output.get('expedite'),
                "num_suppliers_available": len(suppliers),
                "critical_decision": True  # Coordinator makes final call
            }
        },
    )

    decision = resolve(response, parse_coordinator, baseline,
                       rule_fields=("decision_type", "quantity", "expedite"))
    meta = decision["meta"]

    # Supplier: the LLM may choose, but only a supplier that exists.
    supplier_id = decision["supplier_id"]
    valid_ids = {s['id'] for s in suppliers}
    if decision["decision_type"] == "HOLD":
        supplier_id = None
    elif supplier_id is None and "decision_type" in meta["disagreements"]:
        # LLM said HOLD but the rules require REORDER: it never picked a supplier.
        supplier_id = baseline["supplier_id"]
    elif supplier_id not in valid_ids:
        if not meta["fallback_used"]:
            meta["output_valid"] = False
            meta["issues"].append(f"LLM selected unknown supplier {supplier_id}; "
                                  f"using supplier {baseline['supplier_id']}")
        supplier_id = baseline["supplier_id"]
    elif supplier_id != baseline["supplier_id"]:
        # Allowed (the prompt permits trade-offs) but worth showing.
        meta["supplier_choice"] = {"llm": supplier_id, "most_reliable": baseline["supplier_id"]}

    # Build final decision structure
    final_decision = {
        'decision_type': decision["decision_type"],
        'details': {
            'supplier_id': supplier_id,
            'quantity': decision["quantity"],
            'expedite': decision["expedite"]
        },
        'explanation': decision["reasoning"],
        'meta': meta,
    }

    return {
        'final_decision': final_decision
    }
