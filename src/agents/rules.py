"""
Deterministic rule baselines for every agent.

Each agent's prompt already spelled out explicit classification rules.
This module encodes those same rules in code. They are used to:

  * answer in offline mode (no API key needed to run or test the system)
  * cross-check live LLM answers; a disagreement is recorded and sends
    the decision to a human
  * provide a safe fallback when the LLM fails or returns malformed output
  * act as the reference answer in the evaluation suite

Thresholds come from config.py so prompts and code cannot drift apart.
"""

from datetime import datetime

import config
from models import utcnow


def demand_rule(snapshot: dict) -> dict:
    """HIGH if stock < reorder point OR there is no active purchase order."""
    inv = snapshot['inventory']
    qty, rop = inv['quantity'], inv['reorder_point']
    n_pos = len(snapshot['purchase_orders'])
    reasons = []
    if qty < rop:
        reasons.append(f"stock {qty} is below the reorder point {rop}")
    if n_pos == 0:
        reasons.append("there are no active purchase orders")
    if reasons:
        return {"demand_risk": "HIGH", "reasoning": "Demand risk is HIGH because " + " and ".join(reasons) + "."}
    return {"demand_risk": "LOW",
            "reasoning": f"Demand risk is LOW: stock {qty} is at or above the reorder point {rop} "
                         f"and {n_pos} purchase order(s) are active."}


def inventory_rule(snapshot: dict) -> dict:
    """
    REORDER if stock < reorder point, topping up to 2x the reorder point
    (original MVP rule). Quantities above config.MAX_ORDER_QUANTITY are
    capped and marked so the decision gate requires a human.
    """
    inv = snapshot['inventory']
    qty, rop = inv['quantity'], inv['reorder_point']
    if qty < rop:
        quantity = rop * 2 - qty
        capped = quantity > config.MAX_ORDER_QUANTITY
        return {"action": "REORDER", "quantity": min(quantity, config.MAX_ORDER_QUANTITY),
                "uncapped_quantity": quantity, "capped": capped}
    return {"action": "HOLD", "quantity": 0, "uncapped_quantity": 0, "capped": False}


def _days_until(eta_iso: str | None, now: datetime) -> int | None:
    if not eta_iso:
        return None
    return (datetime.fromisoformat(eta_iso) - now).days


def risk_rule(snapshot: dict, now: datetime | None = None) -> dict:
    """
    Supplier risk HIGH if any supplier reliability < threshold.
    Logistics risk HIGH if any shipment is > LOGISTICS_MAX_ETA_DAYS away,
    overdue, has no ETA, or if there are no active shipments.
    """
    now = now or utcnow()
    threshold = config.SUPPLIER_RELIABILITY_THRESHOLD
    weak = [s for s in snapshot['suppliers'] if s['reliability_score'] < threshold]
    supplier_risk = "HIGH" if weak else "LOW"

    shipments = snapshot['shipments']
    logistics_reasons = []
    if not shipments:
        logistics_reasons.append("there are no active shipments")
    for sh in shipments:
        days = _days_until(sh.get('expected_arrival'), now)
        if days is None:
            logistics_reasons.append(f"shipment #{sh['id']} has no ETA")
        elif days < 0:
            logistics_reasons.append(f"shipment #{sh['id']} is overdue by {abs(days)} days")
        elif days > config.LOGISTICS_MAX_ETA_DAYS:
            logistics_reasons.append(f"shipment #{sh['id']} arrives in {days} days")
    logistics_risk = "HIGH" if logistics_reasons else "LOW"

    parts = []
    if weak:
        parts.append("Supplier risk is HIGH: " + ", ".join(
            f"{s['name']} at {s['reliability_score']:.0%}" for s in weak) + f" (threshold {threshold:.0%}).")
    else:
        parts.append(f"Supplier risk is LOW: all suppliers are at or above {threshold:.0%} reliability.")
    if logistics_reasons:
        parts.append("Logistics risk is HIGH: " + "; ".join(logistics_reasons) + ".")
    else:
        parts.append(f"Logistics risk is LOW: all shipments arrive within {config.LOGISTICS_MAX_ETA_DAYS} days.")
    return {"supplier_risk": supplier_risk, "logistics_risk": logistics_risk, "reasoning": " ".join(parts)}


def logistics_rule(snapshot: dict, inventory_out: dict, demand_out: dict, risk_out: dict) -> dict:
    """Expedite if any of the three criteria in the logistics prompt is met."""
    inv = snapshot['inventory']
    qty, rop = inv['quantity'], inv['reorder_point']
    reasons = []
    if inventory_out.get('action') == "REORDER" and qty < rop:
        reasons.append("a reorder is needed and stock is below the reorder point")
    if demand_out.get('demand_risk') == "HIGH" and risk_out.get('logistics_risk') == "HIGH":
        reasons.append("demand risk and logistics risk are both HIGH")
    if risk_out.get('supplier_risk') == "HIGH" and qty <= rop * config.NEAR_REORDER_FACTOR:
        reasons.append("supplier risk is HIGH and stock is near the reorder point")
    if reasons:
        return {"expedite": True, "reasoning": "Expedite: " + "; ".join(reasons) +
                ". The extra shipping cost is justified by the stockout risk."}
    return {"expedite": False, "reasoning": "Normal shipping: none of the expedite criteria apply, "
                                            "so the extra cost of expediting is not justified."}


def coordinator_rule(snapshot: dict, agent_outputs: dict) -> dict:
    """
    Follow the coordination rules in the coordinator prompt: decision type
    and quantity come from the inventory agent, the supplier is the most
    reliable one, and expedite follows the logistics agent.
    """
    inventory_out = agent_outputs.get('inventory', {})
    logistics_out = agent_outputs.get('logistics', {})
    if inventory_out.get('action') != "REORDER":
        inv = snapshot['inventory']
        return {"decision_type": "HOLD", "supplier_id": None, "quantity": 0, "expedite": False,
                "reasoning": (f"HOLD: stock is {inv['quantity']} against a reorder point of "
                              f"{inv['reorder_point']}, so the inventory agent found no purchase order is needed. "
                              "Other risk signals are recorded but do not justify ordering on their own.")}
    best = max(snapshot['suppliers'], key=lambda s: s['reliability_score'])
    expedite = bool(logistics_out.get('expedite'))
    return {
        "decision_type": "REORDER", "supplier_id": best['id'], "quantity": inventory_out['quantity'],
        "expedite": expedite,
        "reasoning": (f"REORDER {inventory_out['quantity']} units (inventory agent quantity) from "
                      f"{best['name']} (supplier {best['id']}), the most reliable supplier at "
                      f"{best['reliability_score']:.0%}. Expedite={expedite} per the logistics agent. "
                      f"Stock is {snapshot['inventory']['quantity']} against a reorder point of "
                      f"{snapshot['inventory']['reorder_point']}."),
    }
