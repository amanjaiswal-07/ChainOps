from state import SupplyChainState
from llm_config import invoke_llm
from agents.outputs import parse_logistics, resolve
from agents.rules import logistics_rule


async def logistics_agent_node(state: SupplyChainState) -> dict:
    """
    Decide whether to expedite shipping using LLM reasoning.

    LLM evaluates:
    - Inventory urgency (from inventory agent)
    - Risk levels (from risk agent)
    - Cost vs speed trade-off

    The expedite flag is checked against rules.logistics_rule. On a
    mismatch the rule wins and the disagreement is recorded, which sends
    the decision to a human.
    """
    snapshot = state['db_snapshot']
    agent_outputs = state['agent_outputs']

    # Get previous agent outputs
    inventory_output = agent_outputs.get('inventory', {})
    demand_output = agent_outputs.get('demand', {})
    risk_output = agent_outputs.get('risk', {})

    # Extract relevant data
    inventory_action = inventory_output.get('action', 'UNKNOWN')
    inventory_qty = snapshot['inventory']['quantity']
    reorder_point = snapshot['inventory']['reorder_point']

    demand_risk = demand_output.get('demand_risk', 'UNKNOWN')
    supplier_risk = risk_output.get('supplier_risk', 'UNKNOWN')
    logistics_risk = risk_output.get('logistics_risk', 'UNKNOWN')

    # Build detailed prompt with explicit decision criteria
    prompt = f"""You are a logistics planning expert for a supply chain operation.

CURRENT SITUATION:
- Current inventory: {inventory_qty} units
- Reorder point: {reorder_point} units
- Inventory action recommended: {inventory_action}
- Demand risk: {demand_risk}
- Supplier risk: {supplier_risk}
- Logistics risk: {logistics_risk}

DECISION CRITERIA:

Expedite shipping if ANY of these conditions are true:
1. Inventory action is REORDER AND current inventory < reorder point (urgent replenishment)
2. Demand risk is HIGH AND logistics risk is HIGH (high stockout probability)
3. Supplier risk is HIGH AND inventory is near reorder point (supplier unreliability risk)

Use normal shipping if:
- Inventory is comfortably above reorder point
- All risk levels are LOW
- Cost savings outweigh small time benefit

COST TRADE-OFF:
- Expedited shipping typically costs 2-3x normal shipping
- Saves 2-5 days in transit time
- Only justified when stockout risk is significant

TASK:
1. Evaluate the situation against the decision criteria
2. Decide: should shipping be expedited (true) or normal (false)?
3. Explain the trade-off between cost and urgency in 2-4 sentences

Do not recommend supplier changes or alternative strategies.

FORMAT:
EXPEDITE: [true or false]
REASONING: [Your explanation of the cost vs urgency trade-off]
"""

    baseline = logistics_rule(snapshot, inventory_output, demand_output, risk_output)
    response = invoke_llm(
        "logistics",
        prompt,
        offline_response=f"EXPEDITE: {str(baseline['expedite']).lower()}\nREASONING: {baseline['reasoning']}",
        run_config={
            "run_name": "logistics_agent_expedite_decision",
            "tags": ["logistics", "shipping_decision", "cost_tradeoff"],
            "metadata": {
                "agent": "logistics",
                "inventory_action": inventory_action,
                "demand_risk": demand_risk,
                "supplier_risk": supplier_risk,
                "logistics_risk": logistics_risk,
                "current_inventory": inventory_qty,
                "below_reorder_point": inventory_qty < reorder_point
            }
        },
    )

    return {
        'agent_outputs': {
            'logistics': resolve(response, parse_logistics, baseline, rule_fields=("expedite",))
        }
    }
