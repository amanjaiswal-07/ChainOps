from state import SupplyChainState
from llm_config import get_llm


async def coordinator_agent_node(state: SupplyChainState) -> dict:
    """
    Synthesize all agent outputs into a final procurement decision.
    
    This is the CRITICAL coordination point where:
    - All agent recommendations are combined
    - Conflicts are explicitly resolved
    - Final decision is made with full explanation
    
    LLM handles conflict resolution and step-by-step reasoning.
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
        f"  • Supplier {s['id']} ({s['name']}): "
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
    
    # Invoke LLM for coordination
    llm = get_llm()
    response = llm.invoke(
    prompt,
    config={
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
    }
)

    response_text = response.content
    
    # Parse LLM response
    decision_type = "HOLD"
    supplier_id = None
    quantity = 0
    expedite = False
    explanation = response_text
    
    try:
        lines = response_text.split('\n')
        
        for line in lines:
            line_upper = line.upper()
            
            if "DECISION_TYPE:" in line_upper:
                if "REORDER" in line_upper:
                    decision_type = "REORDER"
                else:
                    decision_type = "HOLD"
            
            elif "SUPPLIER_ID:" in line and decision_type == "REORDER":
                # Extract number
                parts = line.split(':')[1].strip()
                try:
                    supplier_id = int(parts.split()[0])
                except:
                    # Default to highest reliability supplier
                    supplier_id = max(suppliers, key=lambda s: s['reliability_score'])['id']
            
            elif "QUANTITY:" in line_upper:
                parts = line.split(':')[1].strip()
                try:
                    quantity = int(parts.split()[0])
                except:
                    quantity = inventory_output.get('quantity', 0)
            
            elif "EXPEDITE:" in line_upper:
                expedite = "TRUE" in line_upper
        
        # Extract reasoning section
        if "REASONING:" in response_text:
            explanation = response_text.split("REASONING:")[1].strip()
    
    except Exception as e:
        # Fallback: use agent recommendations directly
        if inventory_output.get('action') == 'REORDER':
            decision_type = "REORDER"
            quantity = inventory_output.get('quantity', 0)
            supplier_id = max(suppliers, key=lambda s: s['reliability_score'])['id']
            expedite = logistics_output.get('expedite', False)
        explanation = f"Coordination parsing failed. Using direct agent outputs. Error: {str(e)}\n\n{response_text}"
    
    # Build final decision structure
    final_decision = {
        'decision_type': decision_type,
        'details': {
            'supplier_id': supplier_id,
            'quantity': quantity,
            'expedite': expedite
        },
        'explanation': explanation
    }
    
    return {
        'final_decision': final_decision
    }
