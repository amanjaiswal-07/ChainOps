from datetime import datetime

import config
from state import SupplyChainState
from llm_config import invoke_llm
from models import utcnow
from agents.outputs import parse_risk, resolve
from agents.rules import risk_rule


async def risk_agent_node(state: SupplyChainState) -> dict:
    """
    Assess supplier and shipment risk using LLM reasoning.

    Cross-checked against rules.risk_rule; the LLM may escalate a risk
    level but cannot downgrade one.
    """
    snapshot = state['db_snapshot']
    suppliers = snapshot['suppliers']
    shipments = snapshot['shipments']
    reliability_pct = f"{config.SUPPLIER_RELIABILITY_THRESHOLD:.0%}"
    max_days = config.LOGISTICS_MAX_ETA_DAYS

    # Format supplier data
    supplier_data = "\n".join([
        f"- {s['name']}: reliability {s['reliability_score']:.0%}, "
        f"lead time {s['lead_time_days']} days"
        for s in suppliers
    ])

    # Format shipment data (human-readable with calculated ETA)
    shipment_data = format_shipment_data_for_llm(shipments)

    # Detailed prompt
    prompt = f"""You are a supply chain risk analyst.

SUPPLIER DATA:
{supplier_data}

SHIPMENT DATA:
{shipment_data}

CLASSIFICATION RULES:

Supplier Risk:
- HIGH: any supplier reliability < {reliability_pct}
- LOW: all suppliers reliability >= {reliability_pct}

Logistics Risk:
- HIGH: any shipment arriving > {max_days} days away, overdue, or no active shipments
- LOW: all shipments arriving within {max_days} days with normal status

TASK:
Classify supplier risk and logistics risk as LOW or HIGH.
Explain in 2-3 sentences using specific data.

FORMAT:
SUPPLIER_RISK: [LOW or HIGH]
LOGISTICS_RISK: [LOW or HIGH]
REASONING: [explanation]
"""

    baseline = risk_rule(snapshot)
    response = invoke_llm(
        "risk",
        prompt,
        offline_response=(f"SUPPLIER_RISK: {baseline['supplier_risk']}\n"
                          f"LOGISTICS_RISK: {baseline['logistics_risk']}\n"
                          f"REASONING: {baseline['reasoning']}"),
        run_config={
            "run_name": "risk_agent_assessment",
            "tags": ["risk", "supplier_evaluation", "logistics_evaluation"],
            "metadata": {
                "agent": "risk",
                "num_suppliers": len(suppliers),
                "num_shipments": len(shipments),
                "avg_supplier_reliability": round(
                    sum(s['reliability_score'] for s in suppliers) / len(suppliers), 2
                ) if suppliers else 0,
                "has_overdue_shipments": "overdue" in baseline['reasoning'],
            }
        },
    )

    return {
        'agent_outputs': {
            'risk': resolve(response, parse_risk, baseline, risk_fields=("supplier_risk", "logistics_risk"))
        }
    }


def format_shipment_data_for_llm(shipments):
    """Convert shipments to human-readable format."""
    if not shipments:
        return "No active shipments"

    lines = []
    now = utcnow()

    for sh in shipments:
        eta_str = sh.get('expected_arrival')

        if eta_str:
            try:
                eta = datetime.fromisoformat(eta_str)
                days = (eta - now).days

                if days < 0:
                    eta_text = f"OVERDUE by {abs(days)} days"
                elif days == 0:
                    eta_text = "arriving TODAY"
                else:
                    eta_text = f"arriving in {days} days"
            except ValueError:
                eta_text = "ETA unknown"
        else:
            eta_text = "ETA not set"

        lines.append(f"- Shipment #{sh['id']}: {sh['status']}, {eta_text}")

    return "\n".join(lines)
