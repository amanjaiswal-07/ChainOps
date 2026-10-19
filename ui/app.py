"""
Minimal Streamlit UI for Multi-Agent Supply Chain Control Tower

This is a thin visualization layer over a LangGraph-based multi-agent system.
It does not contain intelligence — it only exposes decisions and reasoning for inspection.
"""

import streamlit as st
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from backend_interface import run_one_cycle

# Page config
st.set_page_config(
    page_title="Supply Chain Control Tower",
    layout="wide"
)

# Title
st.title(" Multi-Agent Supply Chain Control Tower")
st.caption("LangGraph-based decision system with 5 specialized agents")

st.markdown("---")

# Product selection
product_id = st.selectbox(
    "Select Product",
    options=[1, 2, 3],
    format_func=lambda x: f"Product {x} - " + 
        ["Widget A (Standard)", "Widget B (Premium)", "Widget C (Specialized)"][x-1]
)

# Run button
if st.button("Run Supply Chain Decision Cycle", type="primary", use_container_width=True):
    with st.spinner("Executing multi-agent workflow..."):
        try:
            result = run_one_cycle(product_id)
            st.session_state['result'] = result
            st.session_state['executed'] = True
            st.success("✓ Decision cycle completed")
        except Exception as e:
            st.error(f"Workflow failed: {str(e)}")
            st.session_state['executed'] = False

st.markdown("---")

# Display results if available
if st.session_state.get('executed'):
    result = st.session_state['result']
    
    # SECTION 1: Supply Chain State
    st.header("Supply Chain State (Database Snapshot)")
    
    snapshot = result.get('db_snapshot', {})
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Product & Inventory")
        product = snapshot.get('product', {})
        inventory = snapshot.get('inventory', {})
        
        st.write(f"**Product:** {product.get('name', 'N/A')}")
        st.write(f"**SKU:** {product.get('sku', 'N/A')}")
        st.write(f"**Current Stock:** {inventory.get('quantity', 0)} units")
        st.write(f"**Reorder Point:** {inventory.get('reorder_point', 0)} units")
        
        if inventory.get('quantity', 0) < inventory.get('reorder_point', 0):
            st.warning("Below reorder point")
        else:
            st.success("Stock adequate")
    
    with col2:
        st.subheader("Suppliers")
        suppliers = snapshot.get('suppliers', [])
        for s in suppliers:
            st.write(f"**{s['name']}**")
            st.write(f"  - Reliability: {s['reliability_score']:.0%}")
            st.write(f"  - Lead time: {s['lead_time_days']} days")
    
    st.subheader("Active Purchase Orders")
    pos = snapshot.get('purchase_orders', [])
    if pos:
        for po in pos:
            st.write(f"PO #{po['id']}: {po['quantity']} units ({po['status']})")
    else:
        st.write("No active purchase orders")
    
    st.subheader("Active Shipments")
    shipments = snapshot.get('shipments', [])
    if shipments:
        for sh in shipments:
            st.write(f"Shipment #{sh['id']}: {sh['status']}")
    else:
        st.write("No active shipments")
    
    st.markdown("---")
    
    # SECTION 2: Agent Reasoning
    st.header("Agent Reasoning (Multi-Agent Analysis)")
    
    agent_outputs = result.get('agent_outputs', {})
    
    # Demand Agent
    if 'demand' in agent_outputs:
        with st.expander("**1. Demand Agent** - Demand Risk Classification", expanded=True):
            demand = agent_outputs['demand']
            st.write(f"**Risk Level:** {demand.get('demand_risk', 'N/A')}")
            st.write(f"**Reasoning:** {demand.get('reasoning', 'N/A')}")
    
    # Inventory Agent
    if 'inventory' in agent_outputs:
        with st.expander("**2. Inventory Agent** - Reorder Decision", expanded=True):
            inv = agent_outputs['inventory']
            st.write(f"**Action:** {inv.get('action', 'N/A')}")
            st.write(f"**Quantity:** {inv.get('quantity', 0)} units")
            st.write(f"**Reasoning:** {inv.get('reasoning', 'N/A')}")
    
    # Risk Agent
    if 'risk' in agent_outputs:
        with st.expander("**3. Risk Agent** - Supplier & Logistics Risk", expanded=True):
            risk = agent_outputs['risk']
            st.write(f"**Supplier Risk:** {risk.get('supplier_risk', 'N/A')}")
            st.write(f"**Logistics Risk:** {risk.get('logistics_risk', 'N/A')}")
            st.write(f"**Reasoning:** {risk.get('reasoning', 'N/A')}")
    
    # Logistics Agent
    if 'logistics' in agent_outputs:
        with st.expander("**4. Logistics Agent** - Shipping Decision", expanded=True):
            log = agent_outputs['logistics']
            st.write(f"**Expedite Shipping:** {'Yes' if log.get('expedite') else 'No'}")
            st.write(f"**Reasoning:** {log.get('reasoning', 'N/A')}")
    
    # Coordinator Agent (always last)
    st.markdown("---")
    
    # SECTION 3: Final Decision (Visually Distinct)
    st.header("Final Decision (Coordinator Synthesis)")
    
    final_decision = result.get('final_decision')
    
    if final_decision:
        decision_type = final_decision.get('decision_type', 'N/A')
        
        # Decision type with color
        if decision_type == 'REORDER':
            st.success(f"**Decision: {decision_type}**")
        else:
            st.info(f"**Decision: {decision_type}**")
        
        # Details
        details = final_decision.get('details', {})
        if details.get('supplier_id'):
            st.write(f"**Supplier Selected:** #{details.get('supplier_id')}")
            st.write(f"**Quantity to Order:** {details.get('quantity')} units")
            st.write(f"**Expedited Shipping:** {'Yes' if details.get('expedite') else 'No'}")
        
        # Explanation
        st.subheader("Explanation")
        st.text_area(
            "Coordinator Reasoning",
            final_decision.get('explanation', 'N/A'),
            height=200,
            disabled=True
        )
    else:
        st.warning("No final decision generated")
    
    st.markdown("---")
    
    # SECTION 4: Governance Status (Critical for Interviews)
    st.header(" Governance & Safety")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Decision Risk Level", result.get('decision_risk', 'N/A'))
    
    with col2:
        human_approval_required = result.get('decision_risk') == 'HIGH'
        st.metric("Human Approval Required", "Yes" if human_approval_required else "No")
    
    with col3:
        feedback = result.get('human_feedback', 'N/A')
        st.metric("Approval Status", feedback if feedback else "Auto-Approved")
    
    # Execution status
    if 'execution' in agent_outputs:
        exec_result = agent_outputs['execution']
        if exec_result.get('executed'):
            st.success(f"✓ {exec_result.get('message')}")
        else:
            st.warning(f"⚠ {exec_result.get('message')}")

else:
    st.info("Select a product and click 'Run Supply Chain Decision Cycle' to begin")
