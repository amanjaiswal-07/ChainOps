"""
Static Demo Landing Page for Supply Chain Control Tower

This is a snapshot-only version showing pre-captured scenarios.
No LLM calls, no database, no backend required.
Perfect for portfolio demos and deployment showcases.
"""

import streamlit as st

# Page config
st.set_page_config(
    page_title="Supply Chain Control Tower - Demo",
    page_icon="🏭",
    layout="wide"
)

# Mock data for three scenarios (pre-captured outputs)
DEMO_SCENARIOS = {
    1: {
        "name": "Product 1 - Widget A (Standard)",
        "description": "Stable scenario with adequate inventory and reliable supplier",
        "db_snapshot": {
            "product": {"name": "Widget A", "sku": "WGT-A-001"},
            "inventory": {"quantity": 150, "reorder_point": 100},
            "suppliers": [
                {"id": 1, "name": "Reliable Corp", "reliability_score": 0.95, "lead_time_days": 5},
                {"id": 2, "name": "Fast Shipping Inc", "reliability_score": 0.88, "lead_time_days": 3},
                {"id": 3, "name": "Budget Supplies", "reliability_score": 0.72, "lead_time_days": 10}
            ],
            "purchase_orders": [
                {"id": 1, "quantity": 200, "status": "pending", "supplier_name": "Reliable Corp"}
            ],
            "shipments": [
                {"id": 1, "status": "in_transit", "eta": "2 days"}
            ]
        },
        "agent_outputs": {
            "demand": {
                "demand_risk": "LOW",
                "reasoning": "Current stock (150 units) is above reorder point (100 units) and there is an active purchase order for 200 units. Demand conditions are stable."
            },
            "inventory": {
                "action": "HOLD",
                "quantity": 0,
                "reasoning": "Current inventory of 150 units exceeds the reorder point of 100 units by 50 units. With an active PO for 200 units, no immediate reorder is necessary."
            },
            "risk": {
                "supplier_risk": "LOW",
                "logistics_risk": "LOW",
                "reasoning": "Primary supplier (Reliable Corp) has 95% reliability score. Active shipment is in transit with 2-day ETA, well within acceptable timeframe."
            },
            "logistics": {
                "expedite": False,
                "reasoning": "Standard shipping is sufficient. Inventory is above reorder point, demand risk is low, and current shipment ETA is acceptable. Expediting would add unnecessary cost."
            }
        },
        "final_decision": {
            "decision_type": "HOLD",
            "details": {
                "supplier_id": None,
                "quantity": 0,
                "expedite": False
            },
            "explanation": "After analyzing all factors, the system recommends HOLD. Current inventory levels are adequate (150 units vs 100 reorder point), an active purchase order for 200 units is already in transit, and all risk indicators are low. The demand agent classified risk as LOW, inventory agent determined no reorder is needed, risk agent found both supplier and logistics risk to be LOW. No action is required at this time."
        },
        "decision_risk": "LOW",
        "human_feedback": None,
        "execution": {
            "executed": False,
            "message": "No action required - inventory levels adequate"
        }
    },
    
    2: {
        "name": "Product 2 - Widget B (Premium)",
        "description": "High-risk scenario with low inventory and no active purchase orders",
        "db_snapshot": {
            "product": {"name": "Widget B", "sku": "WGT-B-002"},
            "inventory": {"quantity": 45, "reorder_point": 100},
            "suppliers": [
                {"id": 1, "name": "Reliable Corp", "reliability_score": 0.95, "lead_time_days": 5},
                {"id": 2, "name": "Fast Shipping Inc", "reliability_score": 0.88, "lead_time_days": 3},
                {"id": 3, "name": "Budget Supplies", "reliability_score": 0.72, "lead_time_days": 10}
            ],
            "purchase_orders": [],
            "shipments": []
        },
        "agent_outputs": {
            "demand": {
                "demand_risk": "HIGH",
                "reasoning": "Critical situation: current stock (45 units) is 55 units below reorder point (100 units) and there are NO active purchase orders. Risk of stockout is imminent."
            },
            "inventory": {
                "action": "REORDER",
                "quantity": 150,
                "reasoning": "Immediate reorder required. Current inventory of 45 units is significantly below the 100-unit reorder point. Calculated reorder quantity of 150 units will restore buffer and prevent stockout."
            },
            "risk": {
                "supplier_risk": "LOW",
                "logistics_risk": "MEDIUM",
                "reasoning": "Reliable Corp maintains 95% reliability. However, logistics risk is elevated due to absence of any active shipments and the urgent need for inventory replenishment."
            },
            "logistics": {
                "expedite": True,
                "reasoning": "Expedited shipping is justified given the critical inventory shortage. Current stock is 55% below reorder point with zero inbound orders. Cost of expediting is outweighed by stockout risk."
            }
        },
        "final_decision": {
            "decision_type": "REORDER",
            "details": {
                "supplier_id": 1,
                "quantity": 150,
                "expedite": True
            },
            "explanation": "URGENT REORDER REQUIRED. The demand agent flagged HIGH risk due to inventory at 45% of reorder point with no active POs. Inventory agent calculated optimal reorder quantity of 150 units. Risk agent recommended Reliable Corp (95% reliability, 5-day lead time) as the safest choice despite the urgency. Logistics agent determined expedited shipping is necessary to mitigate stockout risk. Final decision: Order 150 units from Reliable Corp with expedited shipping. This decision requires human approval due to HIGH risk classification and cost implications of expedited delivery."
        },
        "decision_risk": "HIGH",
        "human_feedback": "APPROVED",
        "execution": {
            "executed": True,
            "message": "Purchase order #2 created successfully - 150 units from Reliable Corp (expedited)"
        }
    },
    
    3: {
        "name": "Product 3 - Widget C (Specialized)",
        "description": "Complex scenario with supplier risk and delayed logistics",
        "db_snapshot": {
            "product": {"name": "Widget C", "sku": "WGT-C-003"},
            "inventory": {"quantity": 85, "reorder_point": 100},
            "suppliers": [
                {"id": 1, "name": "Reliable Corp", "reliability_score": 0.95, "lead_time_days": 5},
                {"id": 2, "name": "Fast Shipping Inc", "reliability_score": 0.88, "lead_time_days": 3},
                {"id": 3, "name": "Budget Supplies", "reliability_score": 0.72, "lead_time_days": 10}
            ],
            "purchase_orders": [
                {"id": 3, "quantity": 100, "status": "pending", "supplier_name": "Budget Supplies"}
            ],
            "shipments": [
                {"id": 3, "status": "delayed", "eta": "12 days"}
            ]
        },
        "agent_outputs": {
            "demand": {
                "demand_risk": "MEDIUM",
                "reasoning": "Inventory at 85 units is below the 100-unit reorder point. However, an active PO exists for 100 units, which moderates the risk despite the delayed shipment status."
            },
            "inventory": {
                "action": "REORDER",
                "quantity": 120,
                "reasoning": "Inventory is 15 units below reorder point and the existing PO is delayed. Proactive reorder of 120 units from a more reliable supplier will ensure continuity and offset the risky delayed shipment."
            },
            "risk": {
                "supplier_risk": "HIGH",
                "logistics_risk": "HIGH",
                "reasoning": "Current PO is with Budget Supplies (72% reliability), significantly below the 90% threshold. Shipment is DELAYED with 12-day ETA, exceeding the 7-day acceptable window. Both supplier and logistics channels present elevated risk."
            },
            "logistics": {
                "expedite": True,
                "reasoning": "Given the combination of below-threshold inventory, HIGH supplier risk, and delayed existing shipment, expedited shipping for the new order is recommended to ensure timely replenishment and avoid reliance on the unreliable Budget Supplies shipment."
            }
        },
        "final_decision": {
            "decision_type": "REORDER",
            "details": {
                "supplier_id": 1,
                "quantity": 120,
                "expedite": True
            },
            "explanation": "REORDER WITH RISK MITIGATION. Inventory agent identified need for 120-unit reorder as current stock (85) is below reorder point and existing PO from Budget Supplies is both delayed (12-day ETA) and from a low-reliability supplier (72%). Risk agent flagged HIGH risk in both supplier and logistics dimensions. To mitigate compounding risks, the system recommends switching to Reliable Corp (95% reliability, 5-day standard lead) and expediting the shipment. This dual-supplier strategy ensures coverage: if Budget Supplies delivers late or fails, Reliable Corp's expedited order provides backup. The logistics agent supported expediting due to converging risk factors. Coordinator prioritized supply chain resilience over cost optimization in this scenario."
        },
        "decision_risk": "HIGH",
        "human_feedback": "APPROVED",
        "execution": {
            "executed": True,
            "message": "Purchase order #4 created successfully - 120 units from Reliable Corp (expedited as risk mitigation)"
        }
    }
}

# App title
st.title("Multi-Agent Supply Chain Control Tower")
st.caption("Demo: Pre-captured Decision Scenarios")

st.markdown("""
**This is a static demo showcasing the system's decision-making capabilities.**  
Real deployments use live LLM reasoning via LangGraph. This demo displays pre-captured outputs from three realistic scenarios.
""")

st.markdown("---")

# Scenario selector
scenario_choice = st.selectbox(
    "Select Scenario",
    options=[1, 2, 3],
    format_func=lambda x: DEMO_SCENARIOS[x]["name"]
)

scenario = DEMO_SCENARIOS[scenario_choice]

st.info(f"**Scenario:** {scenario['description']}")

# Display button (cosmetic - data is pre-loaded)
if st.button("View Decision Analysis", type="primary", use_container_width=True):
    st.success("✓ Scenario loaded (pre-captured data)")

st.markdown("---")

# SECTION 1: Supply Chain State
st.header(" Supply Chain State (Database Snapshot)")

snapshot = scenario["db_snapshot"]

col1, col2 = st.columns(2)

with col1:
    st.subheader("Product & Inventory")
    product = snapshot["product"]
    inventory = snapshot["inventory"]
    
    st.write(f"**Product:** {product['name']}")
    st.write(f"**SKU:** {product['sku']}")
    st.write(f"**Current Stock:** {inventory['quantity']} units")
    st.write(f"**Reorder Point:** {inventory['reorder_point']} units")
    
    if inventory['quantity'] < inventory['reorder_point']:
        st.warning("⚠️ Below reorder point")
    else:
        st.success("✓ Stock adequate")

with col2:
    st.subheader("Suppliers")
    for s in snapshot["suppliers"]:
        st.write(f"**{s['name']}**")
        st.write(f"  - Reliability: {s['reliability_score']:.0%}")
        st.write(f"  - Lead time: {s['lead_time_days']} days")

st.subheader("Active Purchase Orders")
pos = snapshot.get("purchase_orders", [])
if pos:
    for po in pos:
        st.write(f"PO #{po['id']}: {po['quantity']} units from {po['supplier_name']} ({po['status']})")
else:
    st.write("No active purchase orders")

st.subheader("Active Shipments")
shipments = snapshot.get("shipments", [])
if shipments:
    for sh in shipments:
        st.write(f"Shipment #{sh['id']}: {sh['status']}, ETA: {sh['eta']}")
else:
    st.write("No active shipments")

st.markdown("---")

# SECTION 2: Agent Reasoning
st.header(" Agent Reasoning (Multi-Agent Analysis)")

agent_outputs = scenario["agent_outputs"]

# Demand Agent
with st.expander("**1. Demand Agent** - Demand Risk Classification", expanded=True):
    demand = agent_outputs['demand']
    if demand['demand_risk'] == "HIGH":
        st.error(f"**Risk Level:** {demand['demand_risk']}")
    elif demand['demand_risk'] == "MEDIUM":
        st.warning(f"**Risk Level:** {demand['demand_risk']}")
    else:
        st.success(f"**Risk Level:** {demand['demand_risk']}")
    st.write(f"**Reasoning:** {demand['reasoning']}")

# Inventory Agent
with st.expander("**2. Inventory Agent** - Reorder Decision", expanded=True):
    inv = agent_outputs['inventory']
    if inv['action'] == "REORDER":
        st.warning(f"**Action:** {inv['action']}")
    else:
        st.success(f"**Action:** {inv['action']}")
    st.write(f"**Quantity:** {inv['quantity']} units")
    st.write(f"**Reasoning:** {inv['reasoning']}")

# Risk Agent
with st.expander("**3. Risk Agent** - Supplier & Logistics Risk", expanded=True):
    risk = agent_outputs['risk']
    st.write(f"**Supplier Risk:** {risk['supplier_risk']}")
    st.write(f"**Logistics Risk:** {risk['logistics_risk']}")
    st.write(f"**Reasoning:** {risk['reasoning']}")

# Logistics Agent
with st.expander("**4. Logistics Agent** - Shipping Decision", expanded=True):
    log = agent_outputs['logistics']
    expedite_text = "Yes ⚡" if log['expedite'] else "No"
    st.write(f"**Expedite Shipping:** {expedite_text}")
    st.write(f"**Reasoning:** {log['reasoning']}")

st.markdown("---")

# SECTION 3: Final Decision
st.header(" Final Decision (Coordinator Synthesis)")

final_decision = scenario["final_decision"]
decision_type = final_decision["decision_type"]

if decision_type == "REORDER":
    st.error(f"**Decision: {decision_type}**")
else:
    st.success(f"**Decision: {decision_type}**")

details = final_decision["details"]
if details.get("supplier_id"):
    supplier_name = next(s['name'] for s in snapshot['suppliers'] if s['id'] == details['supplier_id'])
    st.write(f"**Supplier Selected:** {supplier_name} (ID #{details['supplier_id']})")
    st.write(f"**Quantity to Order:** {details['quantity']} units")
    expedite_icon = "⚡ Yes" if details['expedite'] else "No"
    st.write(f"**Expedited Shipping:** {expedite_icon}")

st.subheader("Explanation")
st.text_area(
    "Coordinator Reasoning",
    final_decision["explanation"],
    height=250,
    disabled=True,
    label_visibility="collapsed"
)

st.markdown("---")

# SECTION 4: Governance
st.header(" Governance & Safety")

col1, col2, col3 = st.columns(3)

with col1:
    risk_level = scenario["decision_risk"]
    if risk_level == "HIGH":
        st.metric("Decision Risk Level", risk_level, delta="Requires Approval", delta_color="inverse")
    else:
        st.metric("Decision Risk Level", risk_level)

with col2:
    human_approval_required = scenario["decision_risk"] == "HIGH"
    st.metric("Human Approval Required", "Yes" if human_approval_required else "No")

with col3:
    feedback = scenario.get("human_feedback")
    status = feedback if feedback else "Auto-Approved"
    st.metric("Approval Status", status)

# Execution status
exec_result = scenario.get("execution", {})
if exec_result.get("executed"):
    st.success(f"✓ {exec_result['message']}")
else:
    st.info(f"ℹ️ {exec_result['message']}")

# Footer
st.markdown("---")
st.caption("""
**About this demo:** This page shows pre-captured outputs from a LangGraph-based multi-agent system.  
In production, 5 LLM-powered agents analyze demand, inventory, supplier risk, logistics, and synthesize decisions in real-time.  
[View full project on GitHub](#) | [Documentation](#)
""")
