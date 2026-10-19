from state import SupplyChainState
from llm_config import get_llm
from datetime import datetime


async def risk_agent_node(state: SupplyChainState) -> dict:
    """Assess supplier and shipment risk using LLM reasoning."""
    
    snapshot = state['db_snapshot']
    suppliers = snapshot['suppliers']
    shipments = snapshot['shipments']
    
    # Format supplier data
    supplier_data = "\n".join([
        f"• {s['name']}: reliability {s['reliability_score']:.0%}, "
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
- HIGH: any supplier reliability < 90%
- LOW: all suppliers reliability >= 90%

Logistics Risk:
- HIGH: any shipment arriving > 7 days away, overdue, or no active shipments
- LOW: all shipments arriving within 7 days with normal status

TASK:
Classify supplier risk and logistics risk as LOW or HIGH.
Explain in 2-3 sentences using specific data.

FORMAT:
SUPPLIER_RISK: [LOW or HIGH]
LOGISTICS_RISK: [LOW or HIGH]
REASONING: [explanation]
"""
    
    llm = get_llm()
    response = llm.invoke(
    prompt,
    config={
        "run_name": "risk_agent_assessment",
        "tags": ["risk", "supplier_evaluation", "logistics_evaluation"],
        "metadata": {
            "agent": "risk",
            "num_suppliers": len(suppliers),
            "num_shipments": len(shipments),
            "avg_supplier_reliability": round(
                sum(s['reliability_score'] for s in suppliers) / len(suppliers), 2
            ) if suppliers else 0,
            "has_overdue_shipments": any(
                sh.get('expected_arrival', '').startswith('-') 
                for sh in shipments
            )
        }
    }
)

    response_text = response.content
    
    # Parse response
    supplier_risk = "UNKNOWN"
    logistics_risk = "UNKNOWN"
    reasoning = response_text
    
    try:
        for line in response_text.split('\n'):
            if "SUPPLIER_RISK:" in line:
                supplier_risk = "HIGH" if "HIGH" in line.upper() else "LOW"
            elif "LOGISTICS_RISK:" in line:
                logistics_risk = "HIGH" if "HIGH" in line.upper() else "LOW"
        
        if "REASONING:" in response_text:
            reasoning = response_text.split("REASONING:")[1].strip()
    except:
        pass
    
    return {
        'agent_outputs': {
            'risk': {
                'supplier_risk': supplier_risk,
                'logistics_risk': logistics_risk,
                'reasoning': reasoning
            }
        }
    }


def format_shipment_data_for_llm(shipments):
    """Convert shipments to human-readable format."""
    if not shipments:
        return "No active shipments"
    
    lines = []
    now = datetime.utcnow()
    
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
            except:
                eta_text = "ETA unknown"
        else:
            eta_text = "ETA not set"
        
        lines.append(f"• Shipment #{sh['id']}: {sh['status']}, {eta_text}")
    
    return "\n".join(lines)
