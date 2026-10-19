from state import SupplyChainState
from llm_config import invoke_llm
from agents.rules import inventory_rule


async def inventory_agent_node(state: SupplyChainState) -> dict:
    """
    Decide whether to reorder using simple deterministic logic,
    then use LLM ONLY to explain why that decision makes sense.

    Logic (code, not LLM, see rules.inventory_rule):
    - If current_quantity < reorder_point -> REORDER up to 2x reorder point
    - Else -> HOLD
    - Quantities above MAX_ORDER_QUANTITY are capped and flagged

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
    decision = inventory_rule(snapshot)
    action, quantity = decision["action"], decision["quantity"]

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

Explain in 2-4 sentences, using clear business reasoning.
Do not recommend any new actions or options.
"""

    offline_reasoning = (
        f"Stock is {current_qty} units against a reorder point of {reorder_point}. "
        + (f"Because stock is below the reorder point, {quantity} units are ordered to bring "
           f"stock back to twice the reorder point." if action == "REORDER"
           else "Stock covers the reorder point, so no order is needed now.")
        + (f" The computed quantity {decision['uncapped_quantity']} exceeds the order ceiling "
           f"and was capped." if decision["capped"] else "")
    )
    response = invoke_llm(
        "inventory",
        prompt,
        offline_response=offline_reasoning,
        run_config={
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
        },
    )

    # The decision itself is deterministic, so only the explanation can fail.
    meta = {"source": response.source, "output_valid": True, "fallback_used": False,
            "issues": [], "disagreements": {}, "deterministic_decision": True}
    reasoning = (response.text or "").strip()
    if response.error or not reasoning:
        meta.update(output_valid=False, fallback_used=True)
        meta["issues"].append(f"LLM explanation unavailable: {response.error or 'empty response'}")
        reasoning = offline_reasoning

    return {
        "agent_outputs": {
            "inventory": {
                "action": action,
                "quantity": quantity,
                "capped": decision["capped"],
                "uncapped_quantity": decision["uncapped_quantity"],
                "reasoning": reasoning,
                "meta": meta,
            }
        }
    }
