from state import SupplyChainState
from llm_config import invoke_llm
from agents.outputs import parse_demand, resolve
from agents.rules import demand_rule


async def demand_agent_node(state: SupplyChainState) -> dict:
    """
    Analyze demand signals using LLM reasoning with explicit criteria.

    The LLM classifies demand risk; the same rules are evaluated in code
    (rules.demand_rule) and the two are reconciled in outputs.resolve():
    the LLM may escalate risk but cannot downgrade it.
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

    baseline = demand_rule(snapshot)
    response = invoke_llm(
        "demand",
        prompt,
        offline_response=f"DEMAND_RISK: {baseline['demand_risk']}\nREASONING: {baseline['reasoning']}",
        run_config={
            "run_name": "demand_agent_analysis",  # Shows up in LangSmith UI
            "tags": ["demand", "risk_classification", "inventory_check"],
            "metadata": {
                "agent": "demand",
                "inventory_level": inventory['quantity'],
                "reorder_point": inventory['reorder_point'],
                "active_pos": len(purchase_orders)
            }
        },
    )

    return {
        'agent_outputs': {
            'demand': resolve(response, parse_demand, baseline, risk_fields=("demand_risk",))
        }
    }
