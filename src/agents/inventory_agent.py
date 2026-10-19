from state import SupplyChainState
from llm_config import get_llm


async def inventory_agent_node(state: SupplyChainState) -> dict:
    """
    Decide whether to reorder using simple deterministic logic,
    then use LLM ONLY to explain why that decision makes sense.

    Logic (code, not LLM):
    - If current_quantity < reorder_point -> REORDER
    - Else -> HOLD

    LLM:
    - Receives the action, quantity, and demand risk
    - Explains the reasoning in natural language
    """
    snapshot = state["db_snapshot"]
    inventory = snapshot["inventory"]
    demand_output = state["agent_outputs"].get("demand", {})

    current_qty = inventory["quantity"]
    reorder_point = inventory["reorder_point"]

    # Deterministic decision (no LLM involved)
    if current_qty < reorder_point:
        action = "REORDER"
        # Simple quantity rule for MVP: top up to 2x reorder point
        quantity = reorder_point * 2 - current_qty
    else:
        action = "HOLD"
        quantity = 0

    demand_risk = demand_output.get("demand_risk", "UNKNOWN")

    # Build detailed explanation prompt (LLM only explains)
    prompt = f"""You are an inventory management expert.

We manage a single product with the following data:

- Current inventory quantity: {current_qty} units
- Reorder point: {reorder_point} units
- Demand risk classification from a separate demand agent: {demand_risk}

An inventory decision has ALREADY been taken by deterministic business logic
based on comparing current stock to the reorder point.

Decision:
- Action: {action}
- Quantity: {quantity} units

Your task is ONLY to explain why this decision is reasonable
given the data above. Do NOT change the decision or suggest alternatives.

Explain in 2–4 sentences, using clear business reasoning.
Do not recommend any new actions or options.
"""

    llm = get_llm()
    response = llm.invoke(
    prompt,
    config={
        "run_name": "inventory_agent_explanation",
        "tags": ["inventory", "reorder_decision", "explanation"],
        "metadata": {
            "agent": "inventory",
            "current_quantity": current_qty,
            "reorder_point": reorder_point,
            "action_taken": action,  # REORDER or HOLD
            "quantity_ordered": quantity,
            "demand_risk": demand_risk,
            "deterministic_logic": True  # Indicates LLM only explains, doesn't decide
        }
    }
)

    reasoning = response.content.strip()

    return {
        "agent_outputs": {
            "inventory": {
                "action": action,
                "quantity": quantity,
                "reasoning": reasoning,
            }
        }
    }
