from langgraph.graph import StateGraph, END
from state import SupplyChainState

# Import all nodes
from nodes.data_ingestion import data_ingestion_node
from nodes.decision_gate import decision_gate_node, should_request_human_approval
from nodes.execution import execution_node
from nodes.human_approval import human_approval_node, post_approval_routing

# Import all agents
from agents.demand_agent import demand_agent_node
from agents.inventory_agent import inventory_agent_node
from agents.risk_agent import risk_agent_node
from agents.logistics_agent import logistics_agent_node
from agents.coordinator_agent import coordinator_agent_node


def create_supply_chain_graph():
    """
    Create the LangGraph workflow for the supply chain control tower.
    
    Flow:
    1. Data Ingestion (read DB snapshot)
    2. Agent Analysis (parallel reasoning):
       - Demand Agent
       - Inventory Agent
       - Risk Agent
       - Logistics Agent
    3. Coordinator Agent (synthesize decision)
    4. Decision Gate (risk-based routing)
    5. Execute OR Human Approval
    6. Loop back to ingestion (continuous monitoring)
    
    Returns:
        Compiled LangGraph StateGraph
    """
    
    # Initialize graph with state schema
    workflow = StateGraph(SupplyChainState)
    
    # ================================================================
    # ADD NODES
    # ================================================================
    
    # Data ingestion (entry point)
    workflow.add_node("ingest_data", data_ingestion_node)
    
    # Agent nodes (reasoning layer)
    workflow.add_node("demand_agent", demand_agent_node)
    workflow.add_node("inventory_agent", inventory_agent_node)
    workflow.add_node("risk_agent", risk_agent_node)
    workflow.add_node("logistics_agent", logistics_agent_node)
    workflow.add_node("coordinator", coordinator_agent_node)
    
    # Decision and execution nodes
    workflow.add_node("decision_gate", decision_gate_node)
    workflow.add_node("execute", execution_node)
    workflow.add_node("human_approval", human_approval_node)
    
    # ================================================================
    # SET ENTRY POINT
    # ================================================================
    
    workflow.set_entry_point("ingest_data")
    
    # ================================================================
    # ADD EDGES (Sequential Flow)
    # ================================================================
    
    # Data ingestion → Demand agent
    workflow.add_edge("ingest_data", "demand_agent")
    
    # Demand agent → Inventory agent
    workflow.add_edge("demand_agent", "inventory_agent")
    
    # Inventory agent → Risk agent
    workflow.add_edge("inventory_agent", "risk_agent")
    
    # Risk agent → Logistics agent
    workflow.add_edge("risk_agent", "logistics_agent")
    
    # Logistics agent → Coordinator
    workflow.add_edge("logistics_agent", "coordinator")
    
    # Coordinator → Decision gate
    workflow.add_edge("coordinator", "decision_gate")
    
    # ================================================================
    # ADD CONDITIONAL EDGES (Branching Logic)
    # ================================================================
    
    # Decision gate → Execute OR Human approval
    workflow.add_conditional_edges(
        "decision_gate",
        should_request_human_approval,  # Returns "auto_execute" or "human_approval"
        {
            "auto_execute": "execute",
            "human_approval": "human_approval"
        }
    )
    
    # Human approval → Execute OR End
    workflow.add_conditional_edges(
        "human_approval",
        post_approval_routing,  # Returns "execute" or "end"
        {
            "execute": "execute",
            "end": END
        }
    )
    
    # Execute → End (could loop back to ingest_data for continuous monitoring)
    workflow.add_edge("execute", END)
    
    # ================================================================
    # COMPILE GRAPH
    # ================================================================
    
    return workflow.compile()


# ================================================================
# OPTIONAL: Continuous Monitoring Loop
# ================================================================

def create_continuous_monitoring_graph():
    """
    Alternative graph with continuous loop.
    After execution, loops back to data ingestion for next cycle.
    
    Use this for real-time monitoring scenarios.
    """
    workflow = StateGraph(SupplyChainState)
    
    # Add all nodes (same as above)
    workflow.add_node("ingest_data", data_ingestion_node)
    workflow.add_node("demand_agent", demand_agent_node)
    workflow.add_node("inventory_agent", inventory_agent_node)
    workflow.add_node("risk_agent", risk_agent_node)
    workflow.add_node("logistics_agent", logistics_agent_node)
    workflow.add_node("coordinator", coordinator_agent_node)
    workflow.add_node("decision_gate", decision_gate_node)
    workflow.add_node("execute", execution_node)
    workflow.add_node("human_approval", human_approval_node)
    
    workflow.set_entry_point("ingest_data")
    
    # Sequential edges
    workflow.add_edge("ingest_data", "demand_agent")
    workflow.add_edge("demand_agent", "inventory_agent")
    workflow.add_edge("inventory_agent", "risk_agent")
    workflow.add_edge("risk_agent", "logistics_agent")
    workflow.add_edge("logistics_agent", "coordinator")
    workflow.add_edge("coordinator", "decision_gate")
    
    # Conditional edges
    workflow.add_conditional_edges(
        "decision_gate",
        should_request_human_approval,
        {
            "auto_execute": "execute",
            "human_approval": "human_approval"
        }
    )
    
    workflow.add_conditional_edges(
        "human_approval",
        post_approval_routing,
        {
            "execute": "execute",
            "end": END
        }
    )
    
    # LOOP BACK: Execute → Ingest (continuous monitoring)
    workflow.add_edge("execute", "ingest_data")
    
    return workflow.compile()
