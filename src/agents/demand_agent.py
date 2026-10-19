from state import SupplyChainState
from llm_config import get_llm


async def demand_agent_node(state: SupplyChainState) -> dict:
    """
    Analyze demand signals using LLM reasoning with explicit criteria.
    """
    snapshot = state['db_snapshot']
    inventory = snapshot['inventory']
    purchase_orders = snapshot['purchase_orders']
    
    # Build context
    po_list = "\n".join([
        f"  - PO #{po['id']}: {po['quantity']} units, status: {po['status']}"
        for po in purchase_orders
    ]) if purchase_orders else "  - No active purchase orders"
    
    # Detailed prompt with explicit rules
    prompt = f"""You are a supply chain demand analyst.

CURRENT DATA:
- Current inventory: {inventory['quantity']} units
- Reorder point: {inventory['reorder_point']} units
- Active purchase orders: {len(purchase_orders)}

{po_list}

CLASSIFICATION RULES:
- HIGH risk if: current quantity < reorder point OR no active purchase orders exist
- LOW risk if: current quantity >= reorder point AND at least one active purchase order exists

TASK:
1. Apply the classification rules above
2. Classify demand risk as LOW or HIGH
3. Explain your reasoning in 2-3 sentences

Do not recommend actions.

FORMAT:
DEMAND_RISK: [LOW or HIGH]
REASONING: [Your explanation based on the rules]
"""
    
    # Invoke LLM
    llm = get_llm()
    response = llm.invoke(
        prompt,
        config={
            "run_name": "demand_agent_analysis",  # Shows up in LangSmith UI
            "tags": ["demand", "risk_classification", "inventory_check"],
            "metadata": {
                "agent": "demand",
                "inventory_level": inventory['quantity'],
                "reorder_point": inventory['reorder_point'],
                "active_pos": len(purchase_orders)
            }
        }
    )
    response_text = response.content
    
    # Parse response
    demand_risk = "UNKNOWN"
    reasoning = response_text
    
    if "DEMAND_RISK:" in response_text and "REASONING:" in response_text:
        parts = response_text.split("REASONING:")
        risk_part = parts[0].replace("DEMAND_RISK:", "").strip()
        reasoning_part = parts[1].strip()
        
        demand_risk = "HIGH" if "HIGH" in risk_part.upper() else "LOW"
        reasoning = reasoning_part
    
    return {
        'agent_outputs': {
            'demand': {
                "demand_risk": demand_risk,
                "reasoning": reasoning
            }
        }
    }
